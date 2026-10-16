import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../state/app_state.dart';

class LoadingView extends StatelessWidget {
  const LoadingView({super.key, this.message});

  final String? message;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const CircularProgressIndicator(),
          if (message != null) ...[
            const SizedBox(height: 16),
            Text(message!, style: Theme.of(context).textTheme.bodyMedium),
          ],
        ],
      ),
    );
  }
}

class MessageView extends StatelessWidget {
  const MessageView({
    super.key,
    required this.icon,
    required this.title,
    this.message,
    this.actionLabel,
    this.onAction,
  });

  final IconData icon;
  final String title;
  final String? message;
  final String? actionLabel;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(32),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 480),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 56, color: theme.colorScheme.outline),
              const SizedBox(height: 16),
              Text(title, style: theme.textTheme.titleLarge, textAlign: TextAlign.center),
              if (message != null) ...[
                const SizedBox(height: 8),
                Text(message!, style: theme.textTheme.bodyMedium, textAlign: TextAlign.center),
              ],
              if (onAction != null) ...[
                const SizedBox(height: 24),
                FilledButton.icon(
                  onPressed: onAction,
                  icon: const Icon(Icons.refresh),
                  label: Text(actionLabel ?? 'Try again'),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class ErrorView extends StatelessWidget {
  const ErrorView({super.key, required this.error, this.onRetry});

  final ApiException error;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final offline = error.kind == ApiErrorKind.network;
    return MessageView(
      icon: offline ? Icons.wifi_off_rounded : Icons.error_outline_rounded,
      title: offline ? 'Campus server not reachable' : 'Something went wrong',
      message: error.message,
      onAction: onRetry,
    );
  }
}

/// Converts anything thrown while loading into an [ApiException] for display.
ApiException asApiException(Object error) => error is ApiException
    ? error
    : const ApiException(ApiErrorKind.server, 'The server sent an unexpected response. Please try again.');

/// Loads data once, shows loading/error states, and lets the builder reload
/// (e.g. from pull-to-refresh). Keeps showing old data if a refresh fails.
class Loader<T> extends StatefulWidget {
  const Loader({super.key, required this.load, required this.builder});

  final Future<T> Function() load;
  final Widget Function(BuildContext context, T data, Future<void> Function() reload) builder;

  @override
  State<Loader<T>> createState() => LoaderState<T>();
}

class LoaderState<T> extends State<Loader<T>> {
  T? _data;
  bool _hasData = false;
  ApiException? _error;

  @override
  void initState() {
    super.initState();
    reload();
  }

  Future<void> reload() async {
    // After sign-out (or an expired session) the login screen is about to replace
    // this one; a reload would only produce a misleading "server not reachable".
    if (!AppScope.read(context).isSignedIn) return;
    if (_error != null) setState(() => _error = null);
    try {
      final data = await widget.load();
      if (!mounted) return;
      setState(() {
        _data = data;
        _hasData = true;
        _error = null;
      });
    } catch (e) {
      if (!mounted || !AppScope.read(context).isSignedIn) return;
      final error = asApiException(e);
      if (_hasData) {
        ScaffoldMessenger.maybeOf(context)?.showSnackBar(SnackBar(content: Text(error.message)));
      } else {
        setState(() => _error = error);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_error != null) return ErrorView(error: _error!, onRetry: reload);
    if (!_hasData) return const LoadingView();
    return widget.builder(context, _data as T, reload);
  }
}
