// End-to-end test of the real app against a running Campus LMS stack.
//
// Requires the Docker stack with demo data (docs/setup-guide.md §5–6) and a device
// or emulator that can reach it. On the Android emulator the host is 10.0.2.2:
//
//   flutter test integration_test/app_flow_test.dart -d emulator-5554 \
//     --dart-define=LMS_SERVER_URL=http://10.0.2.2:8080 \
//     --dart-define=LMS_TEST_PASSWORD=<demo password> [--dart-define=LMS_TEST_USERNAME=e2e.student --dart-define=LMS_TEST_FULL_NAME="E2E Test Student"]
//
// Covers PRD AC-01/02/03/05/06/09 and T-01, T-02, T-04, T-05, T-06, T-07, T-09, T-10, browsing
// Subjects → Modules → Content, and the notes (PDF) viewer.

import 'package:campus_lms/app.dart';
import 'package:campus_lms/player/player_view.dart';
import 'package:campus_lms/state/app_state.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:video_player/video_player.dart';

const _password = String.fromEnvironment('LMS_TEST_PASSWORD');
// A dedicated Class 12 account keeps this test's progress separate from manual testing.
const _username = String.fromEnvironment('LMS_TEST_USERNAME', defaultValue: 'demo.student');
const _fullName = String.fromEnvironment('LMS_TEST_FULL_NAME', defaultValue: 'Demo Student');

/// Pumps frames in real time until [condition] holds (network and video need wall-clock time).
Future<void> pumpUntil(
  WidgetTester tester,
  bool Function() condition, {
  Duration timeout = const Duration(seconds: 60),
  String? reason,
}) async {
  final deadline = DateTime.now().add(timeout);
  while (!condition()) {
    if (DateTime.now().isAfter(deadline)) {
      fail('Timed out after ${timeout.inSeconds}s waiting for: ${reason ?? 'condition'}');
    }
    await tester.pump(const Duration(milliseconds: 100));
    await Future<void>.delayed(const Duration(milliseconds: 200));
  }
  await tester.pump();
}

Future<void> pumpFor(WidgetTester tester, Duration duration) async {
  final end = DateTime.now().add(duration);
  while (DateTime.now().isBefore(end)) {
    await tester.pump(const Duration(milliseconds: 100));
    await Future<void>.delayed(const Duration(milliseconds: 200));
  }
}

VideoPlayerController? playerController(WidgetTester tester) {
  final finder = find.byType(PlayerView);
  if (finder.evaluate().isEmpty) return null;
  return tester.widget<PlayerView>(finder).controller;
}

Future<void> tapText(WidgetTester tester, String text) async {
  final finder = find.text(text);
  // Wait until the widget can actually receive the tap (menus and routes animate in).
  await pumpUntil(tester, () => finder.hitTestable().evaluate().isNotEmpty, reason: 'text "$text"');
  await pumpFor(tester, const Duration(milliseconds: 350));
  await tester.tap(finder.hitTestable().first);
  await tester.pump();
}

/// Taps a player control, first revealing the auto-hiding controls by tapping an
/// empty part of the video (not the centre, which is the play/pause button).
Future<void> tapPlayerControl(WidgetTester tester, Finder control) async {
  for (var i = 0; i < 5 && control.hitTestable().evaluate().isEmpty; i++) {
    final r = tester.getRect(find.byType(PlayerView));
    await tester.tapAt(Offset(r.left + r.width * 0.15, r.top + r.height * 0.3));
    await pumpFor(tester, const Duration(milliseconds: 400));
  }
  expect(control.hitTestable(), findsWidgets, reason: 'player control $control not reachable');
  await tester.tap(control.hitTestable().first);
  await tester.pump();
}

/// Android system back (gesture or button), as students navigate on tablets.
Future<void> systemBack(WidgetTester tester) async {
  await tester.binding.handlePopRoute();
  await pumpFor(tester, const Duration(milliseconds: 600));
}

/// Opens a video and waits until it is playing past [minSeconds].
Future<VideoPlayerController> openAndWaitForPlayback(WidgetTester tester, String lesson,
    {int minSeconds = 2}) async {
  await tester.ensureVisible(find.text(lesson).first); // module lists build every item
  await tapText(tester, lesson);
  late VideoPlayerController controller;
  await pumpUntil(tester, () {
    final c = playerController(tester);
    if (c == null || !c.value.isInitialized) return false;
    controller = c;
    return c.value.isPlaying;
  }, timeout: const Duration(seconds: 90), reason: '"$lesson" to start playing');
  final start = controller.value.position;
  await pumpUntil(
    tester,
    () => controller.value.position >= start + Duration(seconds: minSeconds),
    reason: '"$lesson" playback position to advance',
  );
  return controller;
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('student signs in, watches, seeks, resumes and signs out', (tester) async {
    expect(_password, isNotEmpty, reason: 'pass --dart-define=LMS_TEST_PASSWORD=<demo password>');

    // Fresh install state.
    final prefs = await SharedPreferences.getInstance();
    await prefs.clear();
    await const FlutterSecureStorage().deleteAll();

    final state = await AppState.load();
    await tester.pumpWidget(CampusLmsApp(state: state));
    await tester.pump();

    // --- Sign-in (T-02 then T-01) ---------------------------------------------
    expect(find.text('Sign in'), findsOneWidget);
    expect(find.textContaining('Server: ${state.serverUrl}'), findsOneWidget);
    final fields = find.byType(TextFormField);
    await tester.enterText(fields.at(0), _username);
    await tester.enterText(fields.at(1), 'definitely-wrong');
    // Submit with the keyboard's Done key: the on-screen keyboard may cover the button.
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await pumpUntil(tester, () => find.text('Incorrect username or password.').evaluate().isNotEmpty,
        reason: 'wrong-password error');

    // After a failed attempt the fields were disabled and re-enabled; tap to focus, as a user would.
    await tester.tap(fields.at(1));
    await tester.pump();
    await tester.enterText(fields.at(1), _password);
    await tester.pump();
    expect(tester.widget<TextFormField>(fields.at(1)).controller!.text == _password, isTrue,
        reason: 'the password field did not take the new text');
    // The on-screen keyboard now covers the button; submit with the keyboard's Done key.
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await pumpUntil(tester, () => find.textContaining('Hello, $_fullName').evaluate().isNotEmpty,
        reason: 'home screen');

    // --- Browsing (T-04, T-05): own class only, draft video hidden ----------------
    // Subjects → Computer Science → module Python Basics → its videos and notes.
    Finder subject(String name) => find.descendant(of: find.byType(GridView), matching: find.text(name));
    await pumpUntil(tester, () => subject('Computer Science').evaluate().isNotEmpty, reason: 'subjects');
    expect(subject('Mathematics'), findsOneWidget);
    expect(find.text('Physics'), findsNothing);

    await tester.tap(subject('Computer Science'));
    await tester.pump();
    await tapText(tester, 'Python Basics'); // the module, on the subject's list of modules
    await pumpUntil(tester, () => find.text('Lesson 2: Python Functions').evaluate().isNotEmpty,
        reason: 'module contents');
    expect(find.text('Lesson 1: Variables and Types'), findsOneWidget);
    expect(find.text('Python Basics: Notes'), findsOneWidget);
    expect(find.textContaining('Lesson 3'), findsNothing);

    // --- Playback, seek, pause (T-06, T-07, T-09, AC-05) -------------------------
    var controller = await openAndWaitForPlayback(tester, 'Lesson 2: Python Functions');
    expect(controller.value.duration.inSeconds, inInclusiveRange(475, 485));

    await controller.seekTo(const Duration(seconds: 240));
    await pumpUntil(
      tester,
      () => controller.value.isPlaying && controller.value.position >= const Duration(seconds: 242),
      reason: 'playback to continue after seeking to 4:00',
    );

    // Speed control through the UI.
    await tapPlayerControl(tester, find.text('1x'));
    await tapText(tester, '1.5x');
    await pumpUntil(tester, () => controller.value.playbackSpeed == 1.5, reason: 'speed 1.5x');

    // Full-screen through the UI, then back.
    await tapPlayerControl(tester, find.byTooltip('Full screen'));
    await pumpUntil(tester, () => tester.widget<PlayerView>(find.byType(PlayerView)).isFullScreen,
        reason: 'full-screen mode');
    expect(find.byType(AppBar), findsNothing);
    await systemBack(tester); // Android back exits full-screen first, not the lesson
    await pumpUntil(tester, () => !tester.widget<PlayerView>(find.byType(PlayerView)).isFullScreen,
        reason: 'exit full-screen');
    expect(find.byType(AppBar), findsOneWidget);

    await controller.pause();
    await pumpFor(tester, const Duration(seconds: 2));
    final pausedAt = controller.value.position.inSeconds;
    expect(pausedAt, greaterThanOrEqualTo(242));

    // --- Leave and reopen: resume within ±10 s (T-10, AC-06, AC-09) -------------
    await systemBack(tester);
    await pumpUntil(tester, () => find.textContaining('Resume at').evaluate().isNotEmpty,
        reason: 'module contents to show the saved position');

    controller = await openAndWaitForPlayback(tester, 'Lesson 2: Python Functions', minSeconds: 1);
    expect(find.textContaining('Resuming from'), findsOneWidget);
    final resumedAt = controller.value.position.inSeconds;
    expect((resumedAt - pausedAt).abs(), lessThanOrEqualTo(10),
        reason: 'resumed at $resumedAt s, paused at $pausedAt s');

    await controller.pause();
    await pumpFor(tester, const Duration(seconds: 1));
    await systemBack(tester);
    await pumpUntil(tester, () => find.text('Lesson 1: Variables and Types').evaluate().isNotEmpty,
        reason: 'back on the module contents');

    // --- Notes (PDF) in the same module: downloaded, rendered on the device -------
    await tester.ensureVisible(find.text('Python Basics: Notes').first);
    await tapText(tester, 'Python Basics: Notes');
    await pumpUntil(tester, () => find.textContaining('Page 1 of').evaluate().isNotEmpty,
        timeout: const Duration(seconds: 90), reason: 'notes viewer page indicator');
    await systemBack(tester);
    await pumpUntil(tester, () => find.text('Opened').evaluate().isNotEmpty,
        reason: 'module contents to show the notes as opened');

    await systemBack(tester);
    await pumpUntil(tester, () => find.text('Python Basics').evaluate().isNotEmpty, reason: 'modules');
    await systemBack(tester);

    // --- Continue Watching and My Learning ------------------------------------
    await pumpUntil(tester, () => find.text('Continue watching').evaluate().isNotEmpty,
        reason: 'Continue watching section');
    await tapText(tester, 'My Learning');
    await pumpUntil(tester, () => find.text('Lesson 2: Python Functions').evaluate().isNotEmpty,
        reason: 'My Learning list');
    expect(find.text('Python Basics: Notes'), findsOneWidget, reason: 'opened notes are in My Learning too');

    // --- Sign out ---------------------------------------------------------------
    await tester.tap(find.byTooltip('Account'));
    await tapText(tester, 'Sign out');
    await pumpUntil(tester, () => find.widgetWithText(FilledButton, 'Sign out').evaluate().isNotEmpty,
        reason: 'confirm dialog');
    await tester.tap(find.widgetWithText(FilledButton, 'Sign out'));
    await pumpUntil(tester, () => find.text('Sign in').evaluate().isNotEmpty, reason: 'login screen after sign-out');
    expect(state.isSignedIn, isFalse);
  });
}
