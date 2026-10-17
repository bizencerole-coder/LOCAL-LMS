import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../api/models.dart';
import '../screens/open_content.dart';
import '../util/format.dart';
import 'content_tile.dart';
import 'layout.dart';

/// A video in progress (or an item opened recently) in the Continue watching row.
class ContinueCard extends StatelessWidget {
  const ContinueCard({super.key, required this.item, required this.onReturn});

  final ContinueItem item;
  final VoidCallback onReturn;

  /// Room for the subject row, two lines of title and the resume line at the student's text size.
  static double height(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return 8 + 32 + // card margins, padding
        math.max(32.0, textLinesHeight(context, text.labelMedium)) +
        10 +
        textLinesHeight(context, text.titleSmall, 2) +
        8 +
        math.max(18.0, textLinesHeight(context, text.bodySmall)) +
        12; // progress bar
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final content = item.content;
    final isVideo = content.type == ContentType.video;
    final fraction = isVideo ? content.progress?.fraction(content.durationSeconds) : null;
    return SizedBox(
      width: 280,
      child: Card(
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: () async {
            await openContentItem(context, content, subtitle: item.location);
            onReturn();
          },
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(children: [
                  ContentTypeIcon(type: content.type, size: 32),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(item.subjectName,
                        style: theme.textTheme.labelMedium, maxLines: 1, overflow: TextOverflow.ellipsis),
                  ),
                ]),
                const SizedBox(height: 10),
                Text(content.title, style: theme.textTheme.titleSmall, maxLines: 2, overflow: TextOverflow.ellipsis),
                const Spacer(),
                Row(children: [
                  Icon(isVideo ? Icons.play_arrow_rounded : Icons.open_in_new_rounded, size: 18),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                        isVideo
                            ? 'Resume at ${formatSeconds(content.progress?.positionSeconds)}'
                            : ContentTypeStyle.of(content.type).label,
                        style: theme.textTheme.bodySmall,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis),
                  ),
                ]),
                if (fraction != null) ...[
                  const SizedBox(height: 8),
                  LinearProgressIndicator(value: fraction, minHeight: 4, borderRadius: BorderRadius.circular(2)),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}
