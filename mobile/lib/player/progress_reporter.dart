import 'dart:async';

import '../config.dart';

/// What the player is doing right now.
class PlaybackSnapshot {
  const PlaybackSnapshot({required this.position, required this.duration, required this.isPlaying});

  final Duration position;
  final Duration duration;
  final bool isPlaying;
}

typedef SaveProgress = Future<void> Function(int positionSeconds, int? durationSeconds, bool completed);

/// Saves playback progress (PRD FR-07):
/// * every [interval] while playing, and whenever [report] is called (pause, exit, end);
/// * never more than one request in flight; the newest pending position wins;
/// * failures are swallowed so playback never stops because a save failed —
///   the next tick retries;
/// * once completion has been requested it is re-sent until a save succeeds, even
///   while the player sits paused at the end.
class ProgressReporter {
  ProgressReporter({
    required this.save,
    required this.snapshot,
    this.interval = AppConfig.progressSaveInterval,
  });

  final SaveProgress save;
  final PlaybackSnapshot? Function() snapshot;
  final Duration interval;

  Timer? _timer;
  int? _savedSeconds;
  bool _savedCompleted = false;
  bool _wantCompleted = false;
  Future<void>? _inFlight;
  (PlaybackSnapshot, bool)? _pending;

  int? get lastSavedSeconds => _savedSeconds;
  bool get isRunning => _timer != null;

  /// Completion was requested but has not reached the server yet.
  bool get completionPending => _wantCompleted && !_savedCompleted;

  /// Starts the periodic timer. Calling again does not add a second timer.
  void start() {
    _timer ??= Timer.periodic(interval, (_) {
      final current = snapshot();
      if (current == null) return;
      if (current.isPlaying || completionPending) report(current);
    });
  }

  void stop() {
    _timer?.cancel();
    _timer = null;
  }

  /// Saves [current]. Returns a future that completes when this position (and any
  /// newer one reported meanwhile) has been sent or has failed.
  Future<void> report(PlaybackSnapshot current, {bool completed = false}) {
    _wantCompleted = _wantCompleted || completed;
    final inFlight = _inFlight;
    if (inFlight != null) {
      _pending = (current, completed);
      return inFlight;
    }
    if (current.position.inSeconds == _savedSeconds && !completionPending) {
      return Future<void>.value();
    }
    return _inFlight = _run(current);
  }

  /// Like [report], but also waits for anything still in flight afterwards.
  Future<void> flush(PlaybackSnapshot current, {bool completed = false}) async {
    await report(current, completed: completed);
    while (_inFlight != null) {
      await _inFlight;
    }
  }

  Future<void> _run(PlaybackSnapshot current) async {
    final seconds = current.position.inSeconds;
    final sendCompleted = completionPending;
    try {
      final duration = current.duration > Duration.zero ? current.duration.inSeconds : null;
      await save(seconds, duration, sendCompleted);
      _savedSeconds = seconds;
      if (sendCompleted) _savedCompleted = true;
    } catch (_) {
      // Tolerated: playback continues and the next report retries.
    } finally {
      _inFlight = null;
    }

    final next = _pending;
    _pending = null;
    if (next != null) await report(next.$1, completed: next.$2);
  }
}

/// Where to start a lesson given its saved progress. A lesson that was watched
/// to (nearly) the end starts again from the beginning; otherwise it resumes a
/// few seconds before the saved point for context.
Duration resumePosition({required int savedSeconds, int? durationSeconds}) {
  if (savedSeconds <= 0) return Duration.zero;
  if (durationSeconds != null && durationSeconds > 0 && savedSeconds >= durationSeconds - 10) {
    return Duration.zero;
  }
  return Duration(seconds: savedSeconds > 3 ? savedSeconds - 3 : 0);
}
