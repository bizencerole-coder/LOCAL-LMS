import 'package:campus_lms/api/models.dart';
import 'package:campus_lms/util/format.dart';
import 'package:campus_lms/widgets/lesson_tile.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('formatDuration', () {
    expect(formatDuration(const Duration(seconds: 5)), '0:05');
    expect(formatDuration(const Duration(minutes: 12, seconds: 45)), '12:45');
    expect(formatDuration(const Duration(hours: 1, minutes: 2, seconds: 9)), '1:02:09');
    expect(formatSeconds(null), '--:--');
  });

  test('formatLength', () {
    expect(formatLength(null), '');
    expect(formatLength(45), '45 s');
    expect(formatLength(720), '12 min');
    expect(formatLength(3900), '1 h 5 min');
    expect(formatLength(7200), '2 h');
  });

  Widget wrap(Widget child) => MaterialApp(home: Scaffold(body: child));

  testWidgets('lesson tile shows resume point for a started lesson', (tester) async {
    await tester.pumpWidget(wrap(LessonTile(
      video: const VideoItem(
        id: 'v1',
        title: 'Python Functions',
        durationSeconds: 1200,
        progress: Progress(positionSeconds: 765, durationSeconds: 1200, isCompleted: false),
      ),
      onTap: () {},
    )));
    expect(find.text('Python Functions'), findsOneWidget);
    expect(find.textContaining('Resume at 12:45'), findsOneWidget);
    expect(find.byType(LinearProgressIndicator), findsOneWidget);
  });

  testWidgets('lesson tile marks completed lessons', (tester) async {
    var tapped = false;
    await tester.pumpWidget(wrap(LessonTile(
      video: const VideoItem(
        id: 'v1',
        title: 'Done',
        durationSeconds: 600,
        progress: Progress(positionSeconds: 600, isCompleted: true),
      ),
      onTap: () => tapped = true,
    )));
    expect(find.textContaining('Watched'), findsOneWidget);
    expect(find.byIcon(Icons.check_rounded), findsOneWidget);
    await tester.tap(find.text('Done'));
    expect(tapped, isTrue);
  });
}
