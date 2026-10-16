import 'dart:async';

import 'package:campus_lms/player/progress_reporter.dart';
import 'package:fake_async/fake_async.dart';
import 'package:flutter_test/flutter_test.dart';

PlaybackSnapshot at(int seconds, {bool playing = true}) => PlaybackSnapshot(
      position: Duration(seconds: seconds),
      duration: const Duration(seconds: 1200),
      isPlaying: playing,
    );

void main() {
  group('resumePosition', () {
    test('starts at zero with no progress', () {
      expect(resumePosition(savedSeconds: 0, durationSeconds: 1200), Duration.zero);
    });
    test('resumes a few seconds before the saved point', () {
      expect(resumePosition(savedSeconds: 765, durationSeconds: 1200), const Duration(seconds: 762));
    });
    test('starts over when the lesson was finished', () {
      expect(resumePosition(savedSeconds: 1195, durationSeconds: 1200), Duration.zero);
    });
    test('works without a known duration', () {
      expect(resumePosition(savedSeconds: 100), const Duration(seconds: 97));
    });
  });

  group('ProgressReporter', () {
    test('saves periodically only while playing', () {
      fakeAsync((async) {
        final saves = <int>[];
        var current = at(0);
        final reporter = ProgressReporter(
          interval: const Duration(seconds: 20),
          snapshot: () => current,
          save: (position, duration, completed) async => saves.add(position),
        )..start();

        current = at(20);
        async.elapse(const Duration(seconds: 20));
        current = at(40);
        async.elapse(const Duration(seconds: 20));
        current = at(40, playing: false);
        async.elapse(const Duration(seconds: 60));
        reporter.stop();
        expect(saves, [20, 40]);
      });
    });

    test('start twice does not create two timers', () {
      fakeAsync((async) {
        var calls = 0;
        var position = 0;
        final reporter = ProgressReporter(
          interval: const Duration(seconds: 20),
          snapshot: () => at(position += 20),
          save: (_, _, _) async => calls++,
        )
          ..start()
          ..start();
        async.elapse(const Duration(seconds: 20));
        reporter.stop();
        expect(calls, 1);
      });
    });

    test('skips unchanged positions but always records completion', () async {
      final saves = <(int, bool)>[];
      final reporter = ProgressReporter(
        snapshot: () => null,
        save: (position, _, completed) async => saves.add((position, completed)),
      );
      await reporter.report(at(100));
      await reporter.report(at(100));
      await reporter.report(at(100), completed: true);
      await reporter.report(at(100), completed: true);
      expect(saves, [(100, false), (100, true)]);
    });

    test('a failed save does not throw and is retried next time', () async {
      var fail = true;
      final saves = <int>[];
      final reporter = ProgressReporter(
        snapshot: () => null,
        save: (position, _, _) async {
          if (fail) throw Exception('offline');
          saves.add(position);
        },
      );
      await reporter.report(at(30));
      expect(reporter.lastSavedSeconds, isNull);
      fail = false;
      await reporter.report(at(30));
      expect(saves, [30]);
    });

    test('flush waits for the in-flight save and then sends the newest position', () async {
      final saves = <int>[];
      final gate = Completer<void>();
      final reporter = ProgressReporter(
        snapshot: () => null,
        save: (position, _, _) async {
          if (position == 10) await gate.future;
          saves.add(position);
        },
      );
      unawaited(reporter.report(at(10)));
      final flushed = reporter.flush(at(25));
      var done = false;
      unawaited(flushed.then((_) => done = true));
      await Future<void>.delayed(Duration.zero);
      expect(done, isFalse, reason: 'flush must wait for the first save');
      gate.complete();
      await flushed;
      expect(saves, [10, 25]);
    });

    test('a failed completion save is retried on the next tick even while paused', () {
      fakeAsync((async) {
        var fail = true;
        final sent = <(int, bool)>[];
        final reporter = ProgressReporter(
          interval: const Duration(seconds: 20),
          snapshot: () => at(1200, playing: false),
          save: (position, _, completed) async {
            if (fail) throw Exception('offline');
            sent.add((position, completed));
          },
        )..start();
        reporter.report(at(1200, playing: false), completed: true); // fails
        async.flushMicrotasks();
        expect(reporter.completionPending, isTrue);
        fail = false;
        async.elapse(const Duration(seconds: 20)); // paused at the end: the tick still retries
        expect(sent, [(1200, true)]);
        expect(reporter.completionPending, isFalse);
        async.elapse(const Duration(seconds: 20)); // nothing new to send
        expect(sent.length, 1);
        reporter.stop();
      });
    });

    test('one request at a time; the newest pending position wins', () async {
      final saves = <int>[];
      final gate = Completer<void>();
      final reporter = ProgressReporter(
        snapshot: () => null,
        save: (position, _, _) async {
          if (saves.isEmpty) await gate.future;
          saves.add(position);
        },
      );
      final first = reporter.report(at(10));
      unawaited(reporter.report(at(20)));
      unawaited(reporter.report(at(30)));
      gate.complete();
      await first;
      expect(saves, [10, 30]);
    });
  });
}
