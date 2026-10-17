import 'package:flutter/material.dart';

import '../api/models.dart';
import '../util/format.dart';

/// A notice in a list: icon, title, the start of the message, when and for whom.
class NoticeTile extends StatelessWidget {
  const NoticeTile({super.key, required this.notice, this.unread = false, this.onTap, this.bodyLines = 2});

  final NoticeItem notice;
  final bool unread;
  final VoidCallback? onTap;
  final int bodyLines;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final important = notice.isImportant;
    // Read out as one item: title, "New", message, when and for whom.
    return MergeSemantics(
      child: Card(
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Container(
                  width: 44,
                  height: 44,
                  decoration: BoxDecoration(
                    color: important ? scheme.errorContainer : scheme.primaryContainer,
                    borderRadius: BorderRadius.circular(14),
                  ),
                  child: Icon(
                    important ? Icons.priority_high_rounded : Icons.campaign_rounded,
                    color: important ? scheme.onErrorContainer : scheme.onPrimaryContainer,
                  ),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Expanded(
                            child: Text(
                              notice.title,
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                              style: theme.textTheme.titleMedium?.copyWith(
                                fontWeight: unread ? FontWeight.w700 : FontWeight.w600,
                              ),
                            ),
                          ),
                          if (unread)
                            Semantics(
                              label: 'New',
                              child: Container(
                                margin: const EdgeInsets.only(left: 8, top: 6),
                                width: 10,
                                height: 10,
                                decoration: BoxDecoration(color: scheme.primary, shape: BoxShape.circle),
                              ),
                            ),
                        ],
                      ),
                      if (notice.body != null && bodyLines > 0) ...[
                        const SizedBox(height: 4),
                        Text(
                          notice.body!,
                          maxLines: bodyLines,
                          overflow: TextOverflow.ellipsis,
                          style: theme.textTheme.bodyMedium?.copyWith(color: scheme.onSurfaceVariant),
                        ),
                      ],
                      const SizedBox(height: 10),
                      NoticeMeta(notice: notice),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// "Important · 3 h ago · Class 12".
class NoticeMeta extends StatelessWidget {
  const NoticeMeta({super.key, required this.notice, this.exactTime = false});

  final NoticeItem notice;
  final bool exactTime;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final style = theme.textTheme.labelMedium?.copyWith(color: scheme.onSurfaceVariant);
    Widget meta(IconData icon, String text) => Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 15, color: scheme.onSurfaceVariant),
        const SizedBox(width: 4),
        Flexible(
          child: Text(text, style: style, overflow: TextOverflow.ellipsis),
        ),
      ],
    );
    return Wrap(
      spacing: 12,
      runSpacing: 6,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        if (notice.isImportant)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
            decoration: BoxDecoration(color: scheme.errorContainer, borderRadius: BorderRadius.circular(999)),
            child: Text(
              'Important',
              style: theme.textTheme.labelSmall?.copyWith(color: scheme.onErrorContainer, fontWeight: FontWeight.w700),
            ),
          ),
        meta(
          Icons.schedule_rounded,
          exactTime ? formatDateTime(notice.publishedAt) : formatRelativeTime(notice.publishedAt),
        ),
        if (notice.audience != null) meta(Icons.groups_rounded, notice.audience!),
      ],
    );
  }
}
