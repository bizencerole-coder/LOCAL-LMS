import 'package:flutter/material.dart';

import '../api/models.dart';
import '../theme.dart';
import '../util/format.dart';
import 'brand.dart';

/// The top of the home page: today's date, a greeting by name, the student's class and
/// how far they are, on the school colour.
class GreetingCard extends StatelessWidget {
  const GreetingCard({
    super.key,
    required this.student,
    this.inProgress = 0,
    this.completed = 0,
    this.total = 0,
    this.now,
  });

  final Student? student;
  final int inProgress;
  final int completed;
  final int total;

  /// For tests; the tablet's clock otherwise.
  final DateTime? now;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final brand = brandOf(context);
    final time = now ?? DateTime.now();
    final name = student?.fullName ?? '';
    final group = student?.groupLabel ?? '';
    final white70 = Colors.white.withValues(alpha: 0.78);
    return Container(
      decoration: BoxDecoration(
        gradient: heroGradient(brand),
        borderRadius: BorderRadius.circular(24),
        boxShadow: [
          BoxShadow(color: heroColors(brand).$2.withValues(alpha: 0.28), blurRadius: 24, offset: const Offset(0, 10)),
        ],
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(24),
        child: Stack(
          children: [
            const Positioned.fill(child: HeroDecoration()),
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 22, 24, 24),
              child: LayoutBuilder(builder: (context, constraints) {
                final hello = Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(formatDayHeading(time),
                        style: theme.textTheme.labelLarge?.copyWith(color: white70, letterSpacing: 0.2)),
                    const SizedBox(height: 6),
                    Text(
                      name.isEmpty ? greetingFor(time) : '${greetingFor(time)}, ${firstNameOf(name)}',
                      style: theme.textTheme.headlineMedium?.copyWith(color: Colors.white),
                    ),
                    if (group.isNotEmpty) ...[
                      const SizedBox(height: 12),
                      _Pill(icon: Icons.school_rounded, text: group),
                    ],
                  ],
                );
                if (total == 0) return hello;
                final stats = Wrap(
                  spacing: 12,
                  runSpacing: 12,
                  children: [
                    _Stat(value: '$inProgress', label: 'In progress', icon: Icons.play_circle_rounded),
                    _Stat(value: '$completed / $total', label: 'Completed', icon: Icons.task_alt_rounded),
                  ],
                );
                // Side by side on tablets, so the banner and notices fit on the first screen.
                if (constraints.maxWidth >= 720) {
                  return Row(children: [Expanded(child: hello), const SizedBox(width: 20), stats]);
                }
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [hello, const SizedBox(height: 20), stats],
                );
              }),
            ),
          ],
        ),
      ),
    );
  }
}

class _Pill extends StatelessWidget {
  const _Pill({required this.icon, required this.text});

  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.16),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(icon, size: 16, color: Colors.white),
        const SizedBox(width: 6),
        Flexible(
          child: Text(text,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.labelLarge?.copyWith(color: Colors.white)),
        ),
      ]),
    );
  }
}

class _Stat extends StatelessWidget {
  const _Stat({required this.value, required this.label, required this.icon});

  final String value;
  final String label;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      constraints: const BoxConstraints(minWidth: 150),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.white.withValues(alpha: 0.18)),
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(icon, color: Colors.white, size: 22),
        const SizedBox(width: 10),
        Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
          Text(value, style: theme.textTheme.titleMedium?.copyWith(color: Colors.white, fontWeight: FontWeight.w700)),
          Text(label, style: theme.textTheme.labelMedium?.copyWith(color: Colors.white.withValues(alpha: 0.78))),
        ]),
      ]),
    );
  }
}
