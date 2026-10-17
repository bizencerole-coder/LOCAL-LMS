import 'package:campus_lms/api/models.dart';
import 'package:campus_lms/util/format.dart';
import 'package:campus_lms/widgets/content_tile.dart';
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

  test('formatBytes', () {
    expect(formatBytes(null), '');
    expect(formatBytes(0), '');
    expect(formatBytes(512), '512 B');
    expect(formatBytes(850 * 1024), '850 KB');
    expect(formatBytes(2411725), '2.3 MB');
    expect(formatBytes(12 * 1024 * 1024), '12 MB');
    expect(formatBytes(150 * 1024 * 1024), '150 MB');
    expect(formatBytes(3 * 1024 * 1024 * 1024), '3 GB');
  });

  test('contentCounts', () {
    expect(contentCounts(videos: 6, notes: 2, total: 8), '6 videos · 2 notes');
    expect(contentCounts(videos: 1, notes: 1, images: 1, total: 3), '1 video · 1 note · 1 image');
    expect(contentCounts(videos: 2, total: 3), '2 videos · 1 other item');
    expect(contentCounts(total: 2), '2 items');
    expect(contentCounts(), '');
  });

  Widget wrap(Widget child) => MaterialApp(home: Scaffold(body: child));

  ContentItem item(ContentType type, {String title = 'Item', int? duration, int? size, Progress? progress}) =>
      ContentItem(
        id: 'c1',
        type: type,
        title: title,
        durationSeconds: duration,
        fileSizeBytes: size,
        progress: progress,
      );

  group('ContentTile', () {
    testWidgets('a started video shows its length, the resume point and a progress bar', (tester) async {
      await tester.pumpWidget(wrap(ContentTile(
        content: item(ContentType.video,
            title: 'Python Functions',
            duration: 1200,
            progress: const Progress(positionSeconds: 765, durationSeconds: 1200, isCompleted: false)),
        onTap: () {},
      )));
      expect(find.text('Python Functions'), findsOneWidget);
      expect(find.text('Video · 20 min'), findsOneWidget);
      expect(find.text('Resume at 12:45'), findsOneWidget);
      final bar = tester.widget<LinearProgressIndicator>(find.byType(LinearProgressIndicator));
      expect(bar.value, closeTo(765 / 1200, 1e-9));
      expect(find.byIcon(Icons.play_circle_outline_rounded), findsOneWidget);
    });

    testWidgets('a finished video is marked as watched, without a progress bar', (tester) async {
      var tapped = false;
      await tester.pumpWidget(wrap(ContentTile(
        content: item(ContentType.video,
            title: 'Done', duration: 600, progress: const Progress(positionSeconds: 600, isCompleted: true)),
        onTap: () => tapped = true,
      )));
      expect(find.text('Watched'), findsOneWidget);
      expect(find.byIcon(Icons.check_circle_rounded), findsOneWidget);
      expect(find.byType(LinearProgressIndicator), findsNothing);
      await tester.tap(find.text('Done'));
      expect(tapped, isTrue);
    });

    testWidgets('a video not started yet shows only its length', (tester) async {
      await tester.pumpWidget(wrap(ContentTile(content: item(ContentType.video, duration: 45), onTap: () {})));
      expect(find.text('Video · 45 s'), findsOneWidget);
      expect(find.textContaining('Resume'), findsNothing);
      expect(find.text('Watched'), findsNothing);
      expect(find.byType(LinearProgressIndicator), findsNothing);
    });

    testWidgets('notes show their size, and "Opened" once opened', (tester) async {
      await tester.pumpWidget(wrap(ContentTile(
        content: item(ContentType.pdf, title: 'Python Basics: Notes', size: 2411725),
        onTap: () {},
      )));
      expect(find.text('PDF · 2.3 MB'), findsOneWidget);
      expect(find.text('Opened'), findsNothing);
      expect(find.byIcon(Icons.description_outlined), findsOneWidget);

      await tester.pumpWidget(wrap(ContentTile(
        content: item(ContentType.pdf,
            title: 'Python Basics: Notes',
            size: 2411725,
            progress: const Progress(positionSeconds: 0, isCompleted: true)),
        onTap: () {},
      )));
      expect(find.text('PDF · 2.3 MB'), findsOneWidget);
      expect(find.text('Opened'), findsOneWidget);
      expect(find.byType(LinearProgressIndicator), findsNothing);
    });

    testWidgets('notes of unknown size just say PDF', (tester) async {
      await tester.pumpWidget(wrap(ContentTile(content: item(ContentType.pdf), onTap: () {})));
      expect(find.text('PDF'), findsOneWidget);
    });

    testWidgets('images say so and can be opened', (tester) async {
      var tapped = false;
      await tester.pumpWidget(wrap(ContentTile(
        content: item(ContentType.image, title: 'Flowchart', size: 300000),
        onTap: () => tapped = true,
      )));
      expect(find.text('Image'), findsOneWidget);
      expect(find.byIcon(Icons.image_outlined), findsOneWidget);
      await tester.tap(find.text('Flowchart'));
      expect(tapped, isTrue);
    });

    testWidgets('an unknown type shows a file icon and the message, and does not open', (tester) async {
      var tapped = false;
      await tester.pumpWidget(wrap(ContentTile(
        content: item(ContentType.unknown, title: 'Quick quiz'),
        onTap: () => tapped = true,
      )));
      expect(find.byIcon(Icons.insert_drive_file_outlined), findsOneWidget);
      expect(find.text("This item can't be opened in this version of the app."), findsOneWidget);
      expect(find.byIcon(Icons.chevron_right_rounded), findsNothing);
      await tester.tap(find.text('Quick quiz'));
      expect(tapped, isFalse);
    });

    testWidgets('My Learning shows where the item lives', (tester) async {
      await tester.pumpWidget(wrap(ContentTile(
        content: item(ContentType.video, duration: 480),
        subtitle: 'Computer Science › Python Basics',
        onTap: () {},
      )));
      expect(find.text('Computer Science › Python Basics'), findsOneWidget);
    });

    testWidgets('long titles and large text do not overflow on a phone', (tester) async {
      tester.view.physicalSize = const Size(1080, 1920); // 360 x 640 dp
      tester.view.devicePixelRatio = 3;
      tester.platformDispatcher.textScaleFactorTestValue = 2;
      addTearDown(tester.view.reset);
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      await tester.pumpWidget(wrap(ListView(children: [
        ContentTile(
          content: item(ContentType.video,
              title: 'Lesson 12: A very long title about recursion and functions',
              duration: 3725,
              progress: const Progress(positionSeconds: 3600, isCompleted: false)),
          subtitle: 'Computer Science › Python Basics and more',
          onTap: () {},
        ),
        ContentTile(content: item(ContentType.unknown, title: 'Something new'), onTap: () {}),
      ])));
      expect(tester.takeException(), isNull);
      expect(find.text('Resume at 1:00:00'), findsOneWidget);
    });
  });
}
