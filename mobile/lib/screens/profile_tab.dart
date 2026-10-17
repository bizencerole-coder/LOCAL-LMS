import 'package:flutter/material.dart';

import '../config.dart';
import '../state/app_state.dart';
import '../widgets/brand.dart';
import '../widgets/layout.dart';

/// The Profile tab: who is signed in, their school, the campus server and sign-out.
class ProfileTab extends StatelessWidget {
  const ProfileTab({super.key, required this.onSignOut});

  final VoidCallback onSignOut;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final state = AppScope.of(context);
    final student = state.student;
    final school = state.school;
    return LayoutBuilder(
      builder: (context, constraints) => SingleChildScrollView(
        padding: readablePadding(constraints.maxWidth, maxWidth: 760, gutter: 20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const PageHeading(title: 'Profile'),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(20),
                child: Row(children: [
                  InitialsAvatar(name: student?.fullName ?? '', size: 64),
                  const SizedBox(width: 18),
                  Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(student?.fullName ?? '', style: theme.textTheme.titleLarge),
                      if ((student?.groupLabel ?? '').isNotEmpty) ...[
                        const SizedBox(height: 4),
                        Text(student!.groupLabel,
                            style: theme.textTheme.bodyMedium?.copyWith(color: scheme.onSurfaceVariant)),
                      ],
                    ]),
                  ),
                ]),
              ),
            ),
            const SizedBox(height: 12),
            _InfoCard(title: 'Account', rows: [
              ('Username', student?.username),
              ('Student ID', student?.studentCode),
              ('Class', student?.className),
              ('Batch', student?.batchName),
            ]),
            const SizedBox(height: 12),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(20),
                child: Row(children: [
                  const SchoolLogo(size: 52),
                  const SizedBox(width: 16),
                  Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(school.name, style: theme.textTheme.titleMedium),
                      if (school.tagline != null)
                        Text(school.tagline!,
                            style: theme.textTheme.bodyMedium?.copyWith(color: scheme.onSurfaceVariant)),
                    ]),
                  ),
                ]),
              ),
            ),
            const SizedBox(height: 12),
            const _ConnectionCard(),
            const SizedBox(height: 12),
            const _InfoCard(title: 'App', rows: [('Version', AppConfig.appVersion)]),
            const SizedBox(height: 24),
            OutlinedButton.icon(
              onPressed: onSignOut,
              style: OutlinedButton.styleFrom(
                foregroundColor: scheme.error,
                side: BorderSide(color: scheme.error.withValues(alpha: 0.5)),
              ),
              icon: const Icon(Icons.logout_rounded),
              label: const Text('Sign out'),
            ),
          ],
        ),
      ),
    );
  }
}

class _InfoCard extends StatelessWidget {
  const _InfoCard({required this.title, required this.rows});

  final String title;
  final List<(String, String?)> rows;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final muted = theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant);
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 16, 20, 12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: theme.textTheme.titleMedium),
          const SizedBox(height: 8),
          for (final (label, value) in rows)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 6),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                SizedBox(width: 120, child: Text(label, style: muted)),
                Expanded(child: Text(value ?? '—', style: theme.textTheme.bodyMedium)),
              ]),
            ),
        ]),
      ),
    );
  }
}

/// The campus server's address and whether it answers, with a re-check button.
class _ConnectionCard extends StatelessWidget {
  const _ConnectionCard();

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final state = AppScope.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 16, 12, 16),
        child: ValueListenableBuilder<bool?>(
          valueListenable: state.serverReachable,
          builder: (context, reachable, _) {
            final (color, label) = switch (reachable) {
              true => (Colors.green.shade600, 'Connected'),
              false => (scheme.error, 'Not reachable'),
              null => (scheme.outline, 'Checking…'),
            };
            return Row(children: [
              Icon(Icons.dns_rounded, color: scheme.onSurfaceVariant),
              const SizedBox(width: 14),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('Campus server', style: theme.textTheme.titleMedium),
                  Text(state.serverUrl,
                      style: theme.textTheme.bodyMedium?.copyWith(color: scheme.onSurfaceVariant)),
                  const SizedBox(height: 4),
                  Row(children: [
                    Icon(Icons.circle, size: 10, color: color),
                    const SizedBox(width: 6),
                    Text(label, style: theme.textTheme.labelMedium),
                  ]),
                ]),
              ),
              TextButton(onPressed: () => state.api.ping(), child: const Text('Check')),
            ]);
          },
        ),
      ),
    );
  }
}
