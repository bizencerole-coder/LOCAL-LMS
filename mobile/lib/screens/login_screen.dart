import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../state/app_state.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _username = TextEditingController();
  final _password = TextEditingController();
  bool _busy = false;
  bool _obscure = true;
  ApiException? _error;

  @override
  void dispose() {
    _username.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_busy || !_formKey.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await AppScope.read(context).signIn(_username.text, _password.text);
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e);
    } catch (_) {
      if (mounted) {
        setState(() => _error = const ApiException(ApiErrorKind.server, 'Could not sign in. Please try again.'));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _editServer() async {
    final state = AppScope.read(context);
    final updated = await showDialog<String>(
      context: context,
      builder: (_) => _ServerDialog(initial: state.serverUrl, state: state),
    );
    if (updated != null) {
      await state.setServerUrl(updated);
      setState(() => _error = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final state = AppScope.of(context);
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: AutofillGroup(
                child: Form(
                  key: _formKey,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Icon(Icons.school_rounded, size: 64, color: theme.colorScheme.primary),
                      const SizedBox(height: 12),
                      Text('Campus LMS', textAlign: TextAlign.center, style: theme.textTheme.headlineMedium),
                      const SizedBox(height: 4),
                      Text('Sign in for your videos and notes',
                          textAlign: TextAlign.center, style: theme.textTheme.bodyMedium),
                      const SizedBox(height: 32),
                      TextFormField(
                        controller: _username,
                        enabled: !_busy,
                        autofillHints: const [AutofillHints.username],
                        textInputAction: TextInputAction.next,
                        autocorrect: false,
                        decoration: const InputDecoration(
                          labelText: 'Username or student ID',
                          prefixIcon: Icon(Icons.person_outline),
                          border: OutlineInputBorder(),
                        ),
                        validator: (v) => (v == null || v.trim().isEmpty) ? 'Enter your username' : null,
                      ),
                      const SizedBox(height: 16),
                      TextFormField(
                        controller: _password,
                        enabled: !_busy,
                        obscureText: _obscure,
                        autofillHints: const [AutofillHints.password],
                        textInputAction: TextInputAction.done,
                        onFieldSubmitted: (_) => _submit(),
                        decoration: InputDecoration(
                          labelText: 'Password',
                          prefixIcon: const Icon(Icons.lock_outline),
                          border: const OutlineInputBorder(),
                          suffixIcon: IconButton(
                            tooltip: _obscure ? 'Show password' : 'Hide password',
                            icon: Icon(_obscure ? Icons.visibility_outlined : Icons.visibility_off_outlined),
                            onPressed: () => setState(() => _obscure = !_obscure),
                          ),
                        ),
                        validator: (v) => (v == null || v.isEmpty) ? 'Enter your password' : null,
                      ),
                      if (_error != null) ...[
                        const SizedBox(height: 16),
                        _ErrorBanner(error: _error!),
                      ],
                      const SizedBox(height: 24),
                      FilledButton(
                        onPressed: _busy ? null : _submit,
                        style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(52)),
                        child: _busy
                            ? const SizedBox.square(dimension: 24, child: CircularProgressIndicator(strokeWidth: 3))
                            : const Text('Sign in'),
                      ),
                      const SizedBox(height: 32),
                      TextButton.icon(
                        onPressed: _busy ? null : _editServer,
                        icon: const Icon(Icons.dns_outlined, size: 18),
                        label: Text('Server: ${state.serverUrl}'),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _ErrorBanner extends StatelessWidget {
  const _ErrorBanner({required this.error});

  final ApiException error;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: scheme.errorContainer, borderRadius: BorderRadius.circular(8)),
      child: Row(
        children: [
          Icon(error.kind == ApiErrorKind.network ? Icons.wifi_off_rounded : Icons.error_outline,
              color: scheme.onErrorContainer),
          const SizedBox(width: 12),
          Expanded(child: Text(error.message, style: TextStyle(color: scheme.onErrorContainer))),
        ],
      ),
    );
  }
}

class _ServerDialog extends StatefulWidget {
  const _ServerDialog({required this.initial, required this.state});

  final String initial;
  final AppState state;

  @override
  State<_ServerDialog> createState() => _ServerDialogState();
}

class _ServerDialogState extends State<_ServerDialog> {
  late final _controller = TextEditingController(text: widget.initial);
  bool _testing = false;
  String? _result;
  bool? _ok;
  String? _inputError;

  static const _invalidMessage = 'Enter a valid server address, e.g. http://192.168.10.10';

  /// The normalised address, or null (and an inline error) when it is not usable.
  String? _validated() {
    final url = tryNormalizeServerUrl(_controller.text);
    setState(() => _inputError = url == null ? _invalidMessage : null);
    return url;
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _test() async {
    final url = _validated();
    if (url == null) return;
    setState(() {
      _testing = true;
      _result = null;
    });
    final client = widget.state.clientFor(url);
    var ok = false;
    try {
      ok = await client.ping();
    } finally {
      client.close();
      if (mounted) {
        setState(() {
          _testing = false;
          _ok = ok;
          _result = ok ? 'Connected to $url' : 'No answer from $url';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Campus server'),
      content: SizedBox(
        width: 400,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Address of the LMS server on the campus network, for example '
                'http://192.168.10.10 or http://lms.campus.lan'),
            const SizedBox(height: 16),
            TextField(
              controller: _controller,
              keyboardType: TextInputType.url,
              autocorrect: false,
              decoration: InputDecoration(
                labelText: 'Server address',
                border: const OutlineInputBorder(),
                errorText: _inputError,
              ),
              onChanged: (_) {
                if (_inputError != null) setState(() => _inputError = null);
              },
              onSubmitted: (_) => _test(),
            ),
            if (_result != null) ...[
              const SizedBox(height: 12),
              Row(children: [
                Icon(_ok! ? Icons.check_circle : Icons.cancel,
                    color: _ok! ? Colors.green : Theme.of(context).colorScheme.error, size: 18),
                const SizedBox(width: 8),
                Expanded(child: Text(_result!)),
              ]),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: _testing ? null : _test, child: Text(_testing ? 'Testing…' : 'Test connection')),
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(
          onPressed: () {
            final url = _validated();
            if (url != null) Navigator.pop(context, url);
          },
          child: const Text('Save'),
        ),
      ],
    );
  }
}
