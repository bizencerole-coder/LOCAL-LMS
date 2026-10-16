import 'dart:async';

import 'package:flutter/material.dart';
import 'package:video_player/video_player.dart';

import '../util/format.dart';

const _speeds = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0];

/// Video surface with tap-to-show controls: play/pause, ±10 s, seek bar,
/// time, speed and full-screen. Fills its parent; the video keeps its aspect ratio.
class PlayerView extends StatefulWidget {
  const PlayerView({
    super.key,
    required this.controller,
    required this.isFullScreen,
    required this.onToggleFullScreen,
    this.title,
  });

  final VideoPlayerController controller;
  final bool isFullScreen;
  final VoidCallback onToggleFullScreen;
  final String? title;

  @override
  State<PlayerView> createState() => _PlayerViewState();
}

class _PlayerViewState extends State<PlayerView> {
  bool _visible = true;
  Timer? _hideTimer;
  double? _dragMs;

  VideoPlayerController get _c => widget.controller;

  @override
  void initState() {
    super.initState();
    _scheduleHide();
  }

  @override
  void dispose() {
    _hideTimer?.cancel();
    super.dispose();
  }

  void _scheduleHide() {
    _hideTimer?.cancel();
    _hideTimer = Timer(const Duration(seconds: 3), () {
      if (mounted && _c.value.isPlaying && _dragMs == null) setState(() => _visible = false);
    });
  }

  void _interact(VoidCallback action) {
    action();
    setState(() => _visible = true);
    _scheduleHide();
  }

  void _togglePlay(VideoPlayerValue value) => _interact(() {
        if (value.isPlaying) {
          _c.pause();
        } else {
          final atEnd = value.duration > Duration.zero && value.position >= value.duration - const Duration(seconds: 1);
          if (atEnd) _c.seekTo(Duration.zero);
          _c.play();
        }
      });

  void _skip(VideoPlayerValue value, int seconds) => _interact(() {
        var target = value.position + Duration(seconds: seconds);
        if (target < Duration.zero) target = Duration.zero;
        if (target > value.duration) target = value.duration;
        _c.seekTo(target);
      });

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<VideoPlayerValue>(
      valueListenable: _c,
      builder: (context, value, _) {
        final showControls = _visible || !value.isPlaying;
        return GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: () {
            setState(() => _visible = !_visible);
            if (_visible) _scheduleHide();
          },
          child: Stack(
            fit: StackFit.expand,
            children: [
              Center(
                child: AspectRatio(
                  aspectRatio: value.aspectRatio > 0 ? value.aspectRatio : 16 / 9,
                  child: VideoPlayer(_c),
                ),
              ),
              if (value.isBuffering)
                const Center(child: CircularProgressIndicator(color: Colors.white)),
              IgnorePointer(
                ignoring: !showControls,
                child: AnimatedOpacity(
                  opacity: showControls ? 1 : 0,
                  duration: const Duration(milliseconds: 200),
                  child: _controls(context, value),
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  Widget _controls(BuildContext context, VideoPlayerValue value) {
    final durationMs = value.duration.inMilliseconds.toDouble();
    final positionMs = (_dragMs ?? value.position.inMilliseconds.toDouble()).clamp(0.0, durationMs > 0 ? durationMs : 1.0);
    const white = Colors.white;
    const textStyle = TextStyle(color: white, fontFeatures: [FontFeature.tabularFigures()]);

    return DecoratedBox(
      decoration: const BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [Color(0x99000000), Color(0x00000000), Color(0x00000000), Color(0xB3000000)],
          stops: [0, 0.25, 0.6, 1],
        ),
      ),
      child: SafeArea(
        child: Column(
          children: [
            if (widget.isFullScreen && widget.title != null)
              Padding(
                padding: const EdgeInsets.fromLTRB(8, 4, 16, 0),
                child: Row(children: [
                  IconButton(
                    tooltip: 'Exit full screen',
                    color: white,
                    icon: const Icon(Icons.arrow_back),
                    onPressed: widget.onToggleFullScreen,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(widget.title!,
                        style: Theme.of(context).textTheme.titleMedium?.copyWith(color: white),
                        overflow: TextOverflow.ellipsis),
                  ),
                ]),
              ),
            const Spacer(),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                IconButton(
                  tooltip: 'Back 10 seconds',
                  iconSize: 40,
                  color: white,
                  icon: const Icon(Icons.replay_10_rounded),
                  onPressed: () => _skip(value, -10),
                ),
                const SizedBox(width: 32),
                IconButton.filled(
                  tooltip: value.isPlaying ? 'Pause' : 'Play',
                  iconSize: 56,
                  style: IconButton.styleFrom(backgroundColor: Colors.black45, foregroundColor: white),
                  icon: Icon(value.isPlaying ? Icons.pause_rounded : Icons.play_arrow_rounded),
                  onPressed: () => _togglePlay(value),
                ),
                const SizedBox(width: 32),
                IconButton(
                  tooltip: 'Forward 10 seconds',
                  iconSize: 40,
                  color: white,
                  icon: const Icon(Icons.forward_10_rounded),
                  onPressed: () => _skip(value, 10),
                ),
              ],
            ),
            const Spacer(),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 8, 4),
              child: Row(
                children: [
                  Text(formatDuration(Duration(milliseconds: positionMs.round())), style: textStyle),
                  Expanded(
                    child: SliderTheme(
                      data: SliderTheme.of(context).copyWith(
                        activeTrackColor: white,
                        inactiveTrackColor: Colors.white38,
                        thumbColor: white,
                        overlayColor: Colors.white24,
                      ),
                      child: Slider(
                        value: positionMs,
                        max: durationMs > 0 ? durationMs : 1.0,
                        onChangeStart: (v) {
                          _hideTimer?.cancel();
                          setState(() => _dragMs = v);
                        },
                        onChanged: (v) => setState(() => _dragMs = v),
                        onChangeEnd: (v) {
                          _c.seekTo(Duration(milliseconds: v.round()));
                          setState(() => _dragMs = null);
                          _scheduleHide();
                        },
                      ),
                    ),
                  ),
                  Text(formatDuration(value.duration), style: textStyle),
                  PopupMenuButton<double>(
                    tooltip: 'Playback speed',
                    initialValue: value.playbackSpeed,
                    onOpened: () => _hideTimer?.cancel(),
                    onCanceled: _scheduleHide,
                    onSelected: (speed) => _interact(() => _c.setPlaybackSpeed(speed)),
                    itemBuilder: (_) => [
                      for (final s in _speeds) PopupMenuItem(value: s, child: Text('${_speedLabel(s)}x')),
                    ],
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                      child: Text('${_speedLabel(value.playbackSpeed)}x',
                          style: textStyle.copyWith(fontWeight: FontWeight.bold)),
                    ),
                  ),
                  IconButton(
                    tooltip: widget.isFullScreen ? 'Exit full screen' : 'Full screen',
                    color: white,
                    icon: Icon(widget.isFullScreen ? Icons.fullscreen_exit_rounded : Icons.fullscreen_rounded),
                    onPressed: () => _interact(widget.onToggleFullScreen),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

String _speedLabel(double speed) =>
    speed == speed.roundToDouble() ? speed.toStringAsFixed(0) : speed.toString();
