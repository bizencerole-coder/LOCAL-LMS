import 'package:flutter/material.dart';

import '../api/models.dart';
import '../screens/subject_screen.dart';
import '../util/format.dart';
import 'catalog_style.dart';
import 'layout.dart';

/// A subject in a grid: its badge, name, what it holds and how far the student got.
class SubjectCard extends StatelessWidget {
  const SubjectCard({super.key, required this.subject, required this.onReturn});

  final SubjectItem subject;
  final VoidCallback onReturn;

  static const _stripe = 6.0;

  /// Room for the stripe, badge row, two lines of name, two of counts and the progress
  /// bar at the student's text size.
  static double height(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return 8 + _stripe + 32 + 44 + 12 + // card margins, stripe, padding, badge row
        textLinesHeight(context, text.titleMedium, 2) +
        6 +
        textLinesHeight(context, text.bodySmall, 2) +
        12 +
        CompletionBar.height(context);
  }

  /// "4 modules · 6 videos · 2 notes".
  String get _summary {
    final counts = contentCounts(
      videos: subject.videoCount,
      notes: subject.notesCount,
      images: subject.imageCount,
      total: subject.contentCount,
    );
    if (subject.moduleCount == 0) return 'No modules yet';
    return [plural(subject.moduleCount, 'module'), if (counts.isNotEmpty) counts].join(' · ');
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final color = subjectColor(subject.name);
    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: () async {
          await Navigator.of(context).push(MaterialPageRoute(builder: (_) => SubjectScreen(subject: subject)));
          onReturn();
        },
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Container(height: _stripe, color: inkOf(color, theme.brightness)),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        SubjectBadge(name: subject.name, size: 44),
                        const Spacer(),
                        Icon(Icons.chevron_right_rounded, color: scheme.onSurfaceVariant),
                      ],
                    ),
                    const SizedBox(height: 12),
                    Text(subject.name,
                        style: theme.textTheme.titleMedium, maxLines: 2, overflow: TextOverflow.ellipsis),
                    const SizedBox(height: 6),
                    Text(
                      _summary,
                      style: theme.textTheme.bodySmall?.copyWith(color: scheme.onSurfaceVariant),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                    const Spacer(),
                    if (subject.contentCount > 0)
                      CompletionBar(completed: subject.completedCount, total: subject.contentCount, color: color),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
