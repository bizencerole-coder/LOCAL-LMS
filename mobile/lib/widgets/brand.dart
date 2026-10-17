import 'package:flutter/material.dart';

import '../state/app_state.dart';
import '../theme.dart';

/// The school's colour (from the dashboard), or the app's own.
Color brandOf(BuildContext context) => brandColor(AppScope.of(context).school.primaryColor);

const _smallWords = {'of', 'the', 'and', 'for', 'at', 'in', '&'};

/// "RP" for "Riverside Public School", "DS" for "Demo Student".
String initialsOf(String name, {int max = 2}) {
  final words = name
      .split(RegExp(r'[\s.\-]+'))
      .where((word) => word.isNotEmpty && !_smallWords.contains(word.toLowerCase()))
      .toList();
  if (words.isEmpty) return '';
  if (words.length == 1 || max == 1) return words.first.characters.first.toUpperCase();
  return (words.first.characters.first + words.last.characters.first).toUpperCase();
}

/// The school's logo from the campus server, or its initials in the school colour.
class SchoolLogo extends StatelessWidget {
  const SchoolLogo({super.key, this.size = 40, this.onColor = false});

  final double size;

  /// Sits on the school colour (drawer, sign-in panel): the fallback is a translucent tile.
  final bool onColor;

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final school = state.school;
    final brand = brandOf(context);
    final radius = BorderRadius.circular(size * 0.28);
    final url = school.logoUrl;
    Widget initials() => Container(
          width: size,
          height: size,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: onColor ? Colors.white.withValues(alpha: 0.18) : heroColors(brand).$1,
            borderRadius: radius,
          ),
          child: Text(
            initialsOf(school.displayName),
            style: TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: size * 0.38, height: 1),
          ),
        );
    if (url == null) return Semantics(label: school.name, child: initials());
    return Container(
      width: size,
      height: size,
      padding: EdgeInsets.all(size * 0.08),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: radius,
        border: onColor ? null : Border.all(color: Theme.of(context).colorScheme.outlineVariant.withValues(alpha: 0.6)),
      ),
      child: Image.network(
        state.api.resolve(url).toString(),
        fit: BoxFit.contain,
        semanticLabel: school.name,
        errorBuilder: (_, _, _) => Icon(Icons.school_rounded, color: brand, size: size * 0.6),
      ),
    );
  }
}

/// A person's initials on a circle.
class InitialsAvatar extends StatelessWidget {
  const InitialsAvatar({super.key, required this.name, this.size = 40, this.background, this.foreground});

  final String name;
  final double size;
  final Color? background;
  final Color? foreground;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final initials = initialsOf(name);
    return Container(
      width: size,
      height: size,
      alignment: Alignment.center,
      decoration: BoxDecoration(color: background ?? scheme.primaryContainer, shape: BoxShape.circle),
      child: initials.isEmpty
          ? Icon(Icons.person_rounded, size: size * 0.55, color: foreground ?? scheme.onPrimaryContainer)
          : Text(
              initials,
              style: TextStyle(
                color: foreground ?? scheme.onPrimaryContainer,
                fontWeight: FontWeight.w700,
                fontSize: size * 0.38,
                height: 1,
              ),
            ),
    );
  }
}

/// Soft circles on a hero card (purely decorative).
class HeroDecoration extends StatelessWidget {
  const HeroDecoration({super.key});

  @override
  Widget build(BuildContext context) {
    Widget circle(double size, double alpha) => Container(
          width: size,
          height: size,
          decoration: BoxDecoration(shape: BoxShape.circle, color: Colors.white.withValues(alpha: alpha)),
        );
    return ExcludeSemantics(
      child: Stack(
        clipBehavior: Clip.hardEdge,
        children: [
          Positioned(right: -60, top: -80, child: circle(220, 0.07)),
          Positioned(right: 70, bottom: -90, child: circle(170, 0.06)),
          Positioned(left: -40, bottom: -60, child: circle(120, 0.04)),
        ],
      ),
    );
  }
}

/// The large title at the top of a tab.
class PageHeading extends StatelessWidget {
  const PageHeading({super.key, required this.title, this.subtitle});

  final String title;
  final String? subtitle;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: 20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: theme.textTheme.headlineSmall),
          if (subtitle != null) ...[
            const SizedBox(height: 4),
            Text(subtitle!, style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
          ],
        ],
      ),
    );
  }
}

/// A section title with an optional "See all" action.
class SectionHeader extends StatelessWidget {
  const SectionHeader({super.key, required this.title, this.subtitle, this.actionLabel = 'See all', this.onAction});

  final String title;
  final String? subtitle;
  final String actionLabel;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: theme.textTheme.titleLarge),
                if (subtitle != null)
                  Text(subtitle!, style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
              ],
            ),
          ),
          if (onAction != null)
            TextButton(
              onPressed: onAction,
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                Text(actionLabel),
                const Icon(Icons.chevron_right_rounded, size: 20),
              ]),
            ),
        ],
      ),
    );
  }
}
