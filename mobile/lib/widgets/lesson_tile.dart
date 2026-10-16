import 'package:flutter/material.dart';

import '../api/models.dart';
import '../util/format.dart';

/// One lesson in a list: title, length, and how far the student got.
class LessonTile extends StatelessWidget {
  const LessonTile({super.key, required this.video, this.subtitle, required this.onTap});

  final VideoItem video;
  final String? subtitle;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final progress = video.progress;
    final fraction = progress?.fraction(video.durationSeconds);
    final completed = progress?.isCompleted ?? false;
    final started = (progress?.positionSeconds ?? 0) > 0;

    final status = completed
        ? 'Watched'
        : started
            ? 'Resume at ${formatSeconds(progress!.positionSeconds)}'
            : null;
    final details = [
      ?subtitle,
      if (formatLength(video.durationSeconds).isNotEmpty) formatLength(video.durationSeconds),
      ?status,
    ].join('  ·  ');

    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
          child: Row(
            children: [
              CircleAvatar(
                backgroundColor: completed ? Colors.green.shade100 : theme.colorScheme.primaryContainer,
                foregroundColor: completed ? Colors.green.shade800 : theme.colorScheme.onPrimaryContainer,
                child: Icon(completed ? Icons.check_rounded : Icons.play_arrow_rounded),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(video.title, style: theme.textTheme.titleMedium),
                    if (details.isNotEmpty) ...[
                      const SizedBox(height: 2),
                      Text(details, style: theme.textTheme.bodySmall),
                    ],
                    if (started && !completed && fraction != null) ...[
                      const SizedBox(height: 8),
                      LinearProgressIndicator(value: fraction, minHeight: 4, borderRadius: BorderRadius.circular(2)),
                    ],
                  ],
                ),
              ),
              const SizedBox(width: 8),
              const Icon(Icons.chevron_right_rounded),
            ],
          ),
        ),
      ),
    );
  }
}
