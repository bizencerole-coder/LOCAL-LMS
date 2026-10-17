import 'package:campus_lms/api/models.dart';
import 'package:campus_lms/widgets/catalog_style.dart';
import 'package:campus_lms/widgets/layout.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

Widget _wrap(Widget child) => MaterialApp(home: Scaffold(body: Padding(padding: const EdgeInsets.all(16), child: child)));

void main() {
  group('CompletionBar', () {
    testWidgets('shows how many are done', (tester) async {
      await tester.pumpWidget(_wrap(const CompletionBar(completed: 2, total: 5)));
      expect(find.text('2 of 5 done'), findsOneWidget);
      final bar = tester.widget<LinearProgressIndicator>(find.byType(LinearProgressIndicator));
      expect(bar.value, closeTo(0.4, 1e-9));
    });

    testWidgets('says when everything is done', (tester) async {
      await tester.pumpWidget(_wrap(const CompletionBar(completed: 3, total: 3, color: Colors.teal)));
      expect(find.text('All 3 done'), findsOneWidget);
      expect(find.byIcon(Icons.check_circle_rounded), findsOneWidget);
    });

    testWidgets('never shows more than the total and nothing for an empty module', (tester) async {
      await tester.pumpWidget(_wrap(const CompletionBar(completed: 9, total: 4)));
      expect(find.text('All 4 done'), findsOneWidget);
      await tester.pumpWidget(_wrap(const CompletionBar(completed: 0, total: 0)));
      expect(find.byType(LinearProgressIndicator), findsNothing);
    });
  });

  test('a subject keeps its colour, whatever the case or spacing', () {
    expect(subjectColor('Computer Science'), same(subjectColor('computer science ')));
    final colours = {for (final name in ['Physics', 'Chemistry', 'Biology', 'Mathematics', 'English']) subjectColor(name)};
    expect(colours.length, greaterThan(1));
  });

  test('lists are centred in a readable column on wide screens only', () {
    expect(readablePadding(400), const EdgeInsets.all(24));
    final wide = readablePadding(1600);
    expect(wide.left, 280);
    expect(wide.right, 280);
    expect(wide.top, 24);
  });

  test('completed counts are read, and default to 0 from older servers', () {
    final subject = SubjectItem.fromJson({
      'id': 's1',
      'name': 'Physics',
      'module_count': 2,
      'content_count': 6,
      'completed_count': 4,
    });
    expect(subject.completedCount, 4);
    final module = ModuleItem.fromJson({'id': 'm1', 'title': 'Motion', 'content_count': 3, 'completed_count': 1});
    expect(module.completedCount, 1);
    expect(ModuleItem.fromJson({'id': 'm2', 'title': 'Old server'}).completedCount, 0);
  });
}
