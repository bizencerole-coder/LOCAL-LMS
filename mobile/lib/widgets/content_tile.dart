import 'package:flutter/material.dart';

import '../api/models.dart';
import '../util/format.dart';

/// Shown for content types added on the server after this version of the app.
const unsupportedContentMessage = "This item can't be opened in this version of the app.";

/// Icon, name and colour of a content type, so videos, notes and images can be told
/// apart at a glance in every list.
class ContentTypeStyle {
  const ContentTypeStyle._(this.icon, this.label, this.color);

  final IconData icon;
  final String label;
  final MaterialColor color;

  static ContentTypeStyle of(ContentType type) => switch (type) {
        ContentType.video => const ContentTypeStyle._(Icons.play_circle_outline_rounded, 'Video', Colors.indigo),
        ContentType.pdf => const ContentTypeStyle._(Icons.description_outlined, 'Notes', Colors.deepOrange),
        ContentType.image => const ContentTypeStyle._(Icons.image_outlined, 'Image', Colors.teal),
        ContentType.unknown => const ContentTypeStyle._(Icons.insert_drive_file_outlined, 'File', Colors.blueGrey),
      };

  Color background(Brightness brightness) =>
      brightness == Brightness.dark ? color.shade700.withValues(alpha: 0.35) : color.shade50;

  Color foreground(Brightness brightness) => brightness == Brightness.dark ? color.shade100 : color.shade700;
}

/// The type's icon on a tinted rounded square.
class ContentTypeIcon extends StatelessWidget {
  const ContentTypeIcon({super.key, required this.type, this.size = 44});

  final ContentType type;
  final double size;

  @override
  Widget build(BuildContext context) {
    final style = ContentTypeStyle.of(type);
    final brightness = Theme.of(context).brightness;
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: style.background(brightness),
        borderRadius: BorderRadius.circular(size * 0.3),
      ),
      child: Icon(style.icon, size: size * 0.55, color: style.foreground(brightness), semanticLabel: style.label),
    );
  }
}

/// Green that reads well on cards in both light and dark mode, for finished items.
Color doneColor(BuildContext context) =>
    Theme.of(context).brightness == Brightness.dark ? Colors.green.shade300 : Colors.green.shade700;

/// One item in a module (or in My Learning): type icon, title, and how far the
/// student got. Videos show their length and resume point, notes their size.
class ContentTile extends StatelessWidget {
  const ContentTile({super.key, required this.content, this.subtitle, required this.onTap});

  final ContentItem content;

  /// Where the item lives, e.g. "Computer Science › Python Basics" in My Learning.
  final String? subtitle;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final muted = theme.colorScheme.onSurfaceVariant;
    final supported = content.type != ContentType.unknown;
    final progress = content.progress;
    final completed = content.isCompleted;
    final isVideo = content.type == ContentType.video;
    final started = isVideo && !completed && (progress?.positionSeconds ?? 0) > 0;
    final fraction = started ? progress!.fraction(content.durationSeconds) : null;

    final details = switch (content.type) {
      ContentType.video => ['Video', formatLength(content.durationSeconds)],
      ContentType.pdf => ['PDF', formatBytes(content.fileSizeBytes)],
      ContentType.image => ['Image'],
      ContentType.unknown => [unsupportedContentMessage],
    }.where((part) => part.isNotEmpty).join(' · ');

    final status = !supported
        ? null
        : completed
            ? (isVideo ? 'Watched' : 'Opened')
            : started
                ? 'Resume at ${formatSeconds(progress!.positionSeconds)}'
                : null;

    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: supported ? onTap : null,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 12, 12),
          child: Row(
            children: [
              ContentTypeIcon(type: content.type),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(content.title, style: theme.textTheme.titleMedium),
                    if (subtitle != null && subtitle!.isNotEmpty) ...[
                      const SizedBox(height: 2),
                      Text(subtitle!, style: theme.textTheme.bodySmall?.copyWith(color: muted)),
                    ],
                    const SizedBox(height: 4),
                    Wrap(
                      spacing: 12,
                      runSpacing: 4,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: [
                        Text(details, style: theme.textTheme.bodySmall?.copyWith(color: muted)),
                        if (status != null) _StatusLabel(text: status, done: completed),
                      ],
                    ),
                    if (fraction != null) ...[
                      const SizedBox(height: 8),
                      LinearProgressIndicator(value: fraction, minHeight: 4, borderRadius: BorderRadius.circular(2)),
                    ],
                  ],
                ),
              ),
              if (supported) ...[
                const SizedBox(width: 8),
                Icon(Icons.chevron_right_rounded, color: muted),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

/// "Resume at 12:45", or "Watched" / "Opened" with a tick.
class _StatusLabel extends StatelessWidget {
  const _StatusLabel({required this.text, required this.done});

  final String text;
  final bool done;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final color = done ? doneColor(context) : theme.colorScheme.primary;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(done ? Icons.check_circle_rounded : Icons.history_rounded, size: 16, color: color),
        const SizedBox(width: 4),
        Flexible(child: Text(text, style: theme.textTheme.labelMedium?.copyWith(color: color))),
      ],
    );
  }
}
