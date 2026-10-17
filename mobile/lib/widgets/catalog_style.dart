import 'package:flutter/material.dart';

import 'layout.dart';

/// Colours for subjects, chosen so text and icons stay readable on their tint in both
/// light and dark mode.
const _subjectPalette = <MaterialColor>[
  Colors.indigo,
  Colors.teal,
  Colors.deepOrange,
  Colors.purple,
  Colors.green,
  Colors.blue,
  Colors.pink,
  Colors.cyan,
  Colors.brown,
  Colors.blueGrey,
];

/// A colour of its own for each subject, the same on every tablet and every visit
/// (derived from the name, not the position in the list).
MaterialColor subjectColor(String name) {
  var hash = 0;
  for (final unit in name.trim().toLowerCase().codeUnits) {
    hash = (hash * 31 + unit) & 0x7fffffff;
  }
  return _subjectPalette[hash % _subjectPalette.length];
}

/// Light background of [color] (a translucent darker shade in dark mode).
Color tintOf(MaterialColor color, Brightness brightness) =>
    brightness == Brightness.dark ? color.shade700.withValues(alpha: 0.35) : color.shade50;

/// Strong shade of [color] for icons and labels on [tintOf] or on cards.
Color inkOf(MaterialColor color, Brightness brightness) =>
    brightness == Brightness.dark ? color.shade100 : color.shade700;

/// The subject's icon on its tinted rounded square.
class SubjectBadge extends StatelessWidget {
  const SubjectBadge({super.key, required this.name, this.size = 44, this.child, this.background});

  final String name;
  final double size;

  /// Instead of the subject's tint, e.g. the surface colour when the badge sits on that tint.
  final Color? background;

  /// Shown instead of the book icon, e.g. a module number.
  final Widget? child;

  @override
  Widget build(BuildContext context) {
    final color = subjectColor(name);
    final brightness = Theme.of(context).brightness;
    final ink = inkOf(color, brightness);
    return Container(
      width: size,
      height: size,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: background ?? tintOf(color, brightness),
        borderRadius: BorderRadius.circular(size * 0.3),
      ),
      child: child == null
          ? Icon(Icons.menu_book_rounded, size: size * 0.52, color: ink)
          : DefaultTextStyle.merge(
              style: TextStyle(color: ink, fontWeight: FontWeight.w600, fontSize: size * 0.4),
              child: child!,
            ),
    );
  }
}

/// "3 of 6 done" (or "All 6 done") above a progress bar, for a subject or a module.
/// Shows nothing for an empty one.
class CompletionBar extends StatelessWidget {
  const CompletionBar({super.key, required this.completed, required this.total, this.color});

  final int completed;
  final int total;

  /// The subject's colour; the theme's primary colour when null.
  final MaterialColor? color;

  @override
  Widget build(BuildContext context) {
    if (total <= 0) return const SizedBox.shrink();
    final theme = Theme.of(context);
    final done = completed.clamp(0, total);
    final brightness = theme.brightness;
    final bar = color == null ? theme.colorScheme.primary : inkOf(color!, brightness);
    final label = done == total ? 'All $total done' : '$done of $total done';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Row(
          children: [
            if (done == total) ...[
              Icon(Icons.check_circle_rounded, size: 16, color: bar),
              const SizedBox(width: 4),
            ],
            Flexible(
              child: Text(label,
                  style: theme.textTheme.labelMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis),
            ),
          ],
        ),
        const SizedBox(height: 6),
        LinearProgressIndicator(
          value: done / total,
          minHeight: 6,
          color: bar,
          backgroundColor: bar.withValues(alpha: 0.15),
          borderRadius: BorderRadius.circular(3),
        ),
      ],
    );
  }

  /// Height of the label and the bar at the student's text size.
  static double height(BuildContext context) =>
      textLinesHeight(context, Theme.of(context).textTheme.labelMedium) + 6 + 6;
}
