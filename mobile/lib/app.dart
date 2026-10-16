import 'package:flutter/material.dart';

import 'screens/home_screen.dart';
import 'screens/login_screen.dart';
import 'state/app_state.dart';

class CampusLmsApp extends StatefulWidget {
  const CampusLmsApp({super.key, required this.state});

  final AppState state;

  @override
  State<CampusLmsApp> createState() => _CampusLmsAppState();
}

class _CampusLmsAppState extends State<CampusLmsApp> {
  final _navigatorKey = GlobalKey<NavigatorState>();
  late bool _signedIn = widget.state.isSignedIn;

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
    final signedIn = widget.state.isSignedIn;
    if (signedIn == _signedIn) return;
    // Signing in or out (including an expired session) returns to the root screen.
    _navigatorKey.currentState?.popUntil((route) => route.isFirst);
    setState(() => _signedIn = signedIn);
  }

  ThemeData _theme(Brightness brightness) => ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF2E5AAC), brightness: brightness),
        useMaterial3: true,
        visualDensity: VisualDensity.comfortable,
      );

  @override
  Widget build(BuildContext context) {
    return AppScope(
      state: widget.state,
      child: MaterialApp(
        title: 'Campus LMS',
        navigatorKey: _navigatorKey,
        debugShowCheckedModeBanner: false,
        theme: _theme(Brightness.light),
        darkTheme: _theme(Brightness.dark),
        home: _signedIn ? const HomeScreen() : const LoginScreen(),
      ),
    );
  }
}
