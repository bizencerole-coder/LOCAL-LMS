import 'package:flutter/material.dart';

import '../state/app_state.dart';

/// Small chip showing whether the campus server answered the last request.
/// Tapping it re-checks. Purely local: no internet check is ever made.
class ConnectionIndicator extends StatelessWidget {
  const ConnectionIndicator({super.key});

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final host = Uri.parse(state.serverUrl).host;
    return ValueListenableBuilder<bool?>(
      valueListenable: state.serverReachable,
      builder: (context, reachable, _) {
        final scheme = Theme.of(context).colorScheme;
        final (color, label) = switch (reachable) {
          true => (Colors.green.shade600, 'Connected'),
          false => (scheme.error, 'Server offline'),
          null => (scheme.outline, 'Checking…'),
        };
        return Tooltip(
          message: 'Campus server $host — tap to re-check',
          child: ActionChip(
            avatar: Icon(Icons.circle, size: 12, color: color),
            label: Text(label),
            onPressed: () => state.api.ping(),
          ),
        );
      },
    );
  }
}
