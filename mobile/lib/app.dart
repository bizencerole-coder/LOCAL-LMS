import 'package:flutter/material.dart';

import 'screens/login_screen.dart';
import 'screens/shell_screen.dart';
import 'state/app_state.dart';
import 'theme.dart';

class CampusLmsApp extends StatefulWidget {
  const CampusLmsApp({super.key, required this.state});

  final AppState state;

  @override
  State<CampusLmsApp> createState() => _CampusLmsAppState();
}

class _CampusLmsAppState extends State<CampusLmsApp> {
  final _navigatorKey = GlobalKey<NavigatorState>();
  late bool _signedIn = widget.state.isSignedIn;
  late Color _brand = _brandOf(widget.state);

  static Color _brandOf(AppState state) => brandColor(state.school.primaryColor);

  @override
  void initState() {
    super.initState();
    widget.state.addListener(_onStateChanged);
  }

  @override
  void dispose() {
    widget.state.removeListener(_onStateChanged);
    super.dispose();
  }

  void _onStateChanged() {
    final brand = _brandOf(widget.state);
    if (brand != _brand) setState(() => _brand = brand);
    final signedIn = widget.state.isSignedIn;
    if (signedIn == _signedIn) return;
    // Signing in or out (including an expired session) returns to the root screen.
    _navigatorKey.currentState?.popUntil((route) => route.isFirst);
    setState(() => _signedIn = signedIn);
  }

  @override
  Widget build(BuildContext context) {
    return AppScope(
      state: widget.state,
      child: MaterialApp(
        title: widget.state.school.displayName,
        navigatorKey: _navigatorKey,
        debugShowCheckedModeBanner: false,
        theme: buildTheme(_brand, Brightness.light),
        darkTheme: buildTheme(_brand, Brightness.dark),
        home: _signedIn ? const ShellScreen() : const LoginScreen(),
      ),
    );
  }
}
