import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:video_player/video_player.dart';
import 'package:wakelock_plus/wakelock_plus.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../config.dart';
import '../player/player_view.dart';
import '../player/progress_reporter.dart';
import '../state/app_state.dart';
import '../util/format.dart';

enum _Phase { loading, ready, error }

/// Opens the player for a lesson. Returns once the student has left it **and** the
/// final progress save has been sent (or has failed), so the caller's lists show
/// the new position when they reload.
Future<void> openLesson(
  BuildContext context, {
  required String videoId,
  required String title,
  String? subtitle,
}) async {
  final pending = await Navigator.of(context).push<Future<void>>(
    MaterialPageRoute(builder: (_) => PlayerScreen(videoId: videoId, title: title, subtitle: subtitle)),
  );
  if (pending != null) {
    try {
      await pending.timeout(AppConfig.requestTimeout + const Duration(seconds: 2));
    } catch (_) {
      // The save itself never throws; this only bounds the wait.
    }
  }
}

/// Plays one lesson (PRD 10.4): asks the API for a signed playback URL, streams
/// it straight from Nginx, resumes from the saved position and saves progress.
class PlayerScreen extends StatefulWidget {
  const PlayerScreen({super.key, required this.videoId, required this.title, this.subtitle});

  final String videoId;
  final String title;
  final String? subtitle;

  @override
  State<PlayerScreen> createState() => _PlayerScreenState();
}

class _PlayerScreenState extends State<PlayerScreen> with WidgetsBindingObserver {
  late final ApiClient _api;
  // The player's own messenger: its notices leave with the player instead of
  // lingering on the lists behind it (they would through the app-wide one).
  final _messengerKey = GlobalKey<ScaffoldMessengerState>();
  VideoPlayerController? _controller;
  ProgressReporter? _reporter;
  PlaybackInfo? _info;
  _Phase _phase = _Phase.loading;
  String? _error;
  bool _fullScreen = false;
  bool _wasPlaying = false;
  bool _completionRequested = false;
  bool _playWhenResumed = false;
  bool _autoRetried = false;
  bool _leftViaPop = false;
  Duration _lastPosition = Duration.zero;
  Duration? _lastDuration;
  int? _durationSeconds;

  /// Incremented on every (re)start and on dispose, so a slow start that
  /// finishes after the user retried or left is discarded.
  int _generation = 0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _api = AppScope.read(context).api;
    _start();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _generation++;
    if (!_leftViaPop) {
      // Removed without going through Back (e.g. the session ended): save what we can.
      final snapshot = _lastKnownSnapshot();
      if (snapshot != null) _reporter?.report(snapshot);
    }
    _releasePlayer();
    WakelockPlus.disable();
    if (_fullScreen) _restoreSystemUi();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Leaving the app pauses the lesson; the pause listener saves progress.
    if (state == AppLifecycleState.paused || state == AppLifecycleState.hidden) {
      _playWhenResumed = false;
      _controller?.pause();
    } else if (state == AppLifecycleState.resumed && _playWhenResumed) {
      _playWhenResumed = false;
      _controller?.play();
    }
  }

  Future<void> _start({Duration? at}) async {
    final generation = ++_generation;
    if (_phase != _Phase.loading) {
      setState(() {
        _phase = _Phase.loading;
        _error = null;
      });
    }
    await _releasePlayer();

    try {
      final info = await _api.authorizePlayback(widget.videoId);
      if (!mounted || generation != _generation) return;
      _info = info;
      _durationSeconds = info.durationSeconds;

      final controller = VideoPlayerController.networkUrl(info.url);
      _controller = controller;
      await controller.initialize().timeout(AppConfig.playerStartTimeout);
      if (_abandoned(generation, controller)) return;

      final resumed = at == null;
      final startAt = at ??
          resumePosition(
            savedSeconds: info.resumePositionSeconds,
            durationSeconds: info.durationSeconds ?? controller.value.duration.inSeconds,
          );
      if (startAt > Duration.zero) {
        await controller.seekTo(startAt);
        if (_abandoned(generation, controller)) return;
      }

      _completionRequested = false;
      _autoRetried = false;
      _wasPlaying = false;
      controller.addListener(_onPlayerUpdate);
      _reporter = ProgressReporter(save: _save, snapshot: _snapshot)..start();
      setState(() => _phase = _Phase.ready);

      // Do not start audio on a tablet that was locked or left while loading.
      if (WidgetsBinding.instance.lifecycleState == AppLifecycleState.resumed) {
        await controller.play();
      } else {
        _playWhenResumed = true;
      }

      if (resumed && startAt > Duration.zero && mounted) {
        _messengerKey.currentState?.showSnackBar(SnackBar(
          content: Text('Resuming from ${formatDuration(startAt)}'),
          duration: const Duration(seconds: 6),
          action: SnackBarAction(
            label: 'Start over',
            onPressed: () {
              if (mounted) _controller?.seekTo(Duration.zero);
            },
          ),
        ));
      }
    } on ApiException catch (e) {
      if (generation == _generation) _fail(e.message);
    } on TimeoutException {
      if (generation == _generation) {
        _fail('The video took too long to start. Check the Wi-Fi connection and try again.');
      }
    } catch (_) {
      if (generation == _generation) {
        _fail('This video could not be played. Check the Wi-Fi connection and try again; '
            'if it keeps happening, tell your teacher.');
      }
    }
  }

  /// True if the screen was left or restarted while [controller] was being set up;
  /// the controller is then released here and the caller must stop.
  bool _abandoned(int generation, VideoPlayerController controller) {
    if (mounted && generation == _generation) return false;
    if (identical(_controller, controller)) _controller = null;
    controller.dispose();
    return true;
  }

  void _onPlayerUpdate() {
    final controller = _controller;
    if (controller == null) return;
    final value = controller.value;

    if (value.hasError) {
      final snapshot = _lastKnownSnapshot();
      if (snapshot != null) _reporter?.report(snapshot);
      final info = _info;
      final urlExpired =
          info != null && DateTime.now().isAfter(info.expiresAt.subtract(const Duration(minutes: 1)));
      if (urlExpired && !_autoRetried) {
        // The signed URL ran out (e.g. after a long pause): get a new one and continue.
        // Deferred: the controller must not be disposed from inside its own listener.
        _autoRetried = true;
        final resumeAt = _lastPosition > Duration.zero ? _lastPosition : null;
        Future.microtask(() => _start(at: resumeAt));
        return;
      }
      _fail('Playback stopped. The connection to the campus server may have dropped.');
      return;
    }
    if (!value.isInitialized) return;
    if (value.position > Duration.zero) _lastPosition = value.position;
    if (value.duration > Duration.zero) _lastDuration = value.duration;

    if (value.isPlaying != _wasPlaying) {
      _wasPlaying = value.isPlaying;
      WakelockPlus.toggle(enable: value.isPlaying);
      final snapshot = _snapshot();
      if (!value.isPlaying && snapshot != null) _reporter?.report(snapshot);
    }

    final atEnd = value.duration > Duration.zero &&
        value.position >= value.duration - const Duration(milliseconds: 500);
    if (atEnd && !value.isPlaying && !_completionRequested) {
      _completionRequested = true;
      final snapshot = _snapshot();
      if (snapshot != null) _reporter?.report(snapshot, completed: true);
    }
  }

  /// The live player state, or null while it is not initialized or has failed.
  PlaybackSnapshot? _snapshot() {
    final controller = _controller;
    if (controller == null) return null;
    final value = controller.value;
    if (!value.isInitialized || value.hasError) return null;
    return PlaybackSnapshot(position: value.position, duration: value.duration, isPlaying: value.isPlaying);
  }

  /// The live state, or the last position seen before an error.
  PlaybackSnapshot? _lastKnownSnapshot() {
    final live = _snapshot();
    if (live != null) return live;
    if (_lastPosition <= Duration.zero) return null;
    return PlaybackSnapshot(position: _lastPosition, duration: _lastDuration ?? Duration.zero, isPlaying: false);
  }

  Future<void> _save(int position, int? duration, bool completed) async {
    await _api.saveProgress(
      widget.videoId,
      positionSeconds: position,
      durationSeconds: duration ?? _durationSeconds,
      completed: completed,
    );
  }

  void _fail(String message) {
    _reporter?.stop();
    WakelockPlus.disable();
    if (!mounted) return;
    setState(() {
      _phase = _Phase.error;
      _error = message;
    });
  }

  Future<void> _releasePlayer() async {
    _reporter?.stop();
    _reporter = null;
    final controller = _controller;
    _controller = null;
    if (controller != null) {
      controller.removeListener(_onPlayerUpdate);
      await controller.dispose();
    }
  }

  /// Retry gets a fresh signed URL (the old one may have expired) and continues
  /// from where playback stopped.
  void _retry() => _start(at: _lastPosition > Duration.zero ? _lastPosition : null);

  /// Back: pause, start the final save, and hand its future to the caller.
  void _leave() {
    _leftViaPop = true;
    _controller?.pause();
    final reporter = _reporter;
    final snapshot = _lastKnownSnapshot();
    final pending = (reporter != null && snapshot != null) ? reporter.flush(snapshot) : Future<void>.value();
    Navigator.of(context).pop<Future<void>>(pending);
  }

  Future<void> _setFullScreen(bool value) async {
    setState(() => _fullScreen = value);
    if (value) {
      await SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky);
      await SystemChrome.setPreferredOrientations([
        DeviceOrientation.landscapeLeft,
        DeviceOrientation.landscapeRight,
      ]);
    } else {
      await _restoreSystemUi();
    }
  }

  Future<void> _restoreSystemUi() async {
    // Manual mode with all overlays restores the app's start-up state on every
    // Android version (edgeToEdge would hide bars on Android 7-9 and force
    // edge-to-edge drawing on 10-14).
    await SystemChrome.setEnabledSystemUIMode(SystemUiMode.manual, overlays: SystemUiOverlay.values);
    await SystemChrome.setPreferredOrientations(const []);
  }

  Widget _videoArea() {
    switch (_phase) {
      case _Phase.ready:
        return PlayerView(
          controller: _controller!,
          isFullScreen: _fullScreen,
          onToggleFullScreen: () => _setFullScreen(!_fullScreen),
          title: widget.title,
        );
      case _Phase.loading:
        return const Center(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            CircularProgressIndicator(color: Colors.white),
            SizedBox(height: 16),
            Text('Loading lesson…', style: TextStyle(color: Colors.white)),
          ]),
        );
      case _Phase.error:
        return Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              const Icon(Icons.error_outline_rounded, color: Colors.white, size: 48),
              const SizedBox(height: 12),
              Text(_error ?? 'Playback failed.',
                  textAlign: TextAlign.center, style: const TextStyle(color: Colors.white)),
              const SizedBox(height: 20),
              Wrap(spacing: 12, children: [
                FilledButton.icon(onPressed: _retry, icon: const Icon(Icons.refresh), label: const Text('Try again')),
                OutlinedButton(
                  style: OutlinedButton.styleFrom(foregroundColor: Colors.white),
                  onPressed: () => _fullScreen ? _setFullScreen(false) : _leave(),
                  child: Text(_fullScreen ? 'Exit full screen' : 'Back'),
                ),
              ]),
            ]),
          ),
        );
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return PopScope(
      // Back is handled here: it leaves full screen first, otherwise it saves and pops.
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (didPop) return;
        if (_fullScreen) {
          _setFullScreen(false);
        } else {
          _leave();
        }
      },
      child: ScaffoldMessenger(
        key: _messengerKey,
        child: _fullScreen
            ? Scaffold(backgroundColor: Colors.black, body: _videoArea())
            : Scaffold(
                appBar: AppBar(title: Text(widget.title)),
                body: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Expanded(child: ColoredBox(color: Colors.black, child: _videoArea())),
                    Padding(
                      padding: const EdgeInsets.fromLTRB(24, 16, 24, 24),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(widget.title, style: theme.textTheme.titleLarge),
                          if (widget.subtitle != null) ...[
                            const SizedBox(height: 4),
                            Text(widget.subtitle!, style: theme.textTheme.bodyMedium),
                          ],
                        ],
                      ),
                    ),
                  ],
                ),
              ),
      ),
    );
  }
}
