import 'dart:async';

import 'package:flutter/material.dart';

import '../api/models.dart';
import '../config.dart';
import '../state/app_state.dart';
import '../theme.dart';
import '../widgets/brand.dart';
import '../widgets/states.dart';
import 'home_tab.dart';
import 'my_learning_screen.dart';
import 'notices_screen.dart';
import 'profile_tab.dart';
import 'subjects_tab.dart';

/// The app's sections, in bottom-bar order.
enum ShellTab {
  home('Home', Icons.home_outlined, Icons.home_rounded),
  subjects('Subjects', Icons.menu_book_outlined, Icons.menu_book_rounded),
  learning('My Learning', Icons.play_circle_outline_rounded, Icons.play_circle_rounded),
  notices('Notices', Icons.notifications_none_rounded, Icons.notifications_rounded),
  profile('Profile', Icons.person_outline_rounded, Icons.person_rounded);

  const ShellTab(this.label, this.icon, this.selectedIcon);

  final String label;
  final IconData icon;
  final IconData selectedIcon;
}

/// What a signed-in student sees: the school's header, a side menu, the bottom bar and
/// the five tabs. Notices are re-checked when the app comes back to the front and every
/// few minutes while it is open, for the bell's count.
class ShellScreen extends StatefulWidget {
  const ShellScreen({super.key});

  static const noticePollInterval = Duration(minutes: 5);

  @override
  State<ShellScreen> createState() => _ShellScreenState();
}

class _ShellScreenState extends State<ShellScreen> with WidgetsBindingObserver {
  final _scaffoldKey = GlobalKey<ScaffoldState>();
  final _homeKey = GlobalKey<HomeTabState>();
  final _subjectsKey = GlobalKey<LoaderState<List<SubjectItem>>>();
  final _learningKey = GlobalKey<LoaderState<List<ContinueItem>>>();
  ShellTab _tab = ShellTab.home;
  Timer? _poll;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final state = AppScope.read(context);
      state.refreshProfile();
      state.refreshSchool();
    });
    _poll = Timer.periodic(ShellScreen.noticePollInterval, (_) => _checkNotices());
  }

  @override
  void dispose() {
    _poll?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState lifecycle) {
    if (lifecycle == AppLifecycleState.resumed) {
      _checkNotices();
      AppScope.read(context).refreshSchool();
    }
  }

  Future<void> _checkNotices() async {
    final state = AppScope.read(context);
    if (!state.isSignedIn) return;
    try {
      await state.loadNotices();
    } catch (_) {
      // Offline or an older server: the bell just keeps its count.
    }
  }

  void _select(ShellTab tab) => setState(() => _tab = tab);

  /// After a lesson: positions and completions may have changed on every tab.
  void _refreshAll() {
    _homeKey.currentState?.reload();
    _subjectsKey.currentState?.reload();
    _learningKey.currentState?.reload();
  }

  Future<void> _confirmSignOut() async {
    final yes = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Sign out?'),
        content: const Text('You will need your password to sign in again.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Sign out')),
        ],
      ),
    );
    if (yes == true && mounted) await AppScope.read(context).signOut();
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    return Scaffold(
      key: _scaffoldKey,
      appBar: _Header(
        onMenu: () => _scaffoldKey.currentState?.openDrawer(),
        onNotices: () => _select(ShellTab.notices),
        onAccount: () => _select(ShellTab.profile),
      ),
      drawer: _SideMenu(
        current: _tab,
        onSelect: (tab) {
          Navigator.pop(context);
          _select(tab);
        },
        onSignOut: () {
          Navigator.pop(context);
          _confirmSignOut();
        },
      ),
      body: IndexedStack(
        index: _tab.index,
        children: [
          HomeTab(
            key: _homeKey,
            onReturn: _refreshAll,
            onSeeAllSubjects: () => _select(ShellTab.subjects),
            onSeeAllNotices: () => _select(ShellTab.notices),
          ),
          SubjectsTab(loaderKey: _subjectsKey, onReturn: _refreshAll),
          MyLearningTab(loaderKey: _learningKey, onReturn: _refreshAll),
          NoticesTab(active: _tab == ShellTab.notices),
          ProfileTab(onSignOut: _confirmSignOut),
        ],
      ),
      bottomNavigationBar: ValueListenableBuilder<int>(
        valueListenable: state.unreadNotices,
        builder: (context, unread, _) => _BottomBar(current: _tab, unread: unread, onSelect: _select),
      ),
    );
  }
}

/// Menu button, the school's logo and name, the connection, the notice bell and the
/// student's initials.
class _Header extends StatelessWidget implements PreferredSizeWidget {
  const _Header({required this.onMenu, required this.onNotices, required this.onAccount});

  final VoidCallback onMenu;
  final VoidCallback onNotices;
  final VoidCallback onAccount;

  @override
  Size get preferredSize => const Size.fromHeight(68);

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final state = AppScope.of(context);
    final school = state.school;
    final wide = MediaQuery.sizeOf(context).width >= 720;
    return AppBar(
      toolbarHeight: 68,
      leading: IconButton(tooltip: 'Menu', icon: const Icon(Icons.menu_rounded), onPressed: onMenu),
      titleSpacing: 0,
      title: Row(children: [
        const SchoolLogo(size: 40),
        const SizedBox(width: 12),
        Flexible(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(school.displayName,
                  maxLines: 1, overflow: TextOverflow.ellipsis, style: theme.textTheme.titleMedium),
              if (school.tagline != null && wide)
                Text(school.tagline!,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.labelMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
            ],
          ),
        ),
      ]),
      actions: [
        _ConnectionDot(label: wide),
        ValueListenableBuilder<int>(
          valueListenable: state.unreadNotices,
          builder: (context, unread, _) => IconButton(
            tooltip: unread == 0 ? 'Notices' : 'Notices, $unread new',
            onPressed: onNotices,
            icon: Badge(
              isLabelVisible: unread > 0,
              label: Text(unread > 9 ? '9+' : '$unread'),
              child: const Icon(Icons.notifications_none_rounded),
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.only(left: 4, right: 12),
          child: IconButton(
            tooltip: 'Account',
            onPressed: onAccount,
            icon: InitialsAvatar(name: state.student?.fullName ?? '', size: 36),
          ),
        ),
      ],
    );
  }
}

/// Whether the campus server answered the last request; tap to re-check.
class _ConnectionDot extends StatelessWidget {
  const _ConnectionDot({required this.label});

  final bool label;

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final scheme = Theme.of(context).colorScheme;
    return ValueListenableBuilder<bool?>(
      valueListenable: state.serverReachable,
      builder: (context, reachable, _) {
        final (color, text) = switch (reachable) {
          true => (Colors.green.shade600, 'Connected'),
          false => (scheme.error, 'Offline'),
          null => (scheme.outline, 'Checking…'),
        };
        final dot = Icon(Icons.circle, size: 10, color: color);
        return Tooltip(
          message: 'Campus server ${Uri.parse(state.serverUrl).host}: $text. Tap to check again.',
          child: label
              ? ActionChip(
                  avatar: dot,
                  label: Text(text),
                  onPressed: () => state.api.ping(),
                  side: BorderSide(color: scheme.outlineVariant),
                  shape: const StadiumBorder(),
                )
              : IconButton(onPressed: () => state.api.ping(), icon: dot),
        );
      },
    );
  }
}

class _BottomBar extends StatelessWidget {
  const _BottomBar({required this.current, required this.unread, required this.onSelect});

  final ShellTab current;
  final int unread;
  final void Function(ShellTab tab) onSelect;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final background = theme.brightness == Brightness.dark ? scheme.surfaceContainer : Colors.white;
    Widget icon(ShellTab tab, IconData data) => tab == ShellTab.notices && unread > 0
        ? Badge(label: Text(unread > 9 ? '9+' : '$unread'), child: Icon(data))
        : Icon(data);
    return DecoratedBox(
      decoration: BoxDecoration(
        color: background,
        border: Border(top: BorderSide(color: scheme.outlineVariant.withValues(alpha: 0.5))),
      ),
      child: Center(
        heightFactor: 1,
        // Five evenly spaced items look scattered across a landscape tablet.
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: NavigationBar(
            selectedIndex: current.index,
            onDestinationSelected: (i) => onSelect(ShellTab.values[i]),
            destinations: [
              for (final tab in ShellTab.values)
                NavigationDestination(
                  icon: icon(tab, tab.icon),
                  selectedIcon: icon(tab, tab.selectedIcon),
                  label: tab.label,
                ),
            ],
          ),
        ),
      ),
    );
  }
}

/// The side menu: the school, the student, the tabs, About and Sign out.
class _SideMenu extends StatelessWidget {
  const _SideMenu({required this.current, required this.onSelect, required this.onSignOut});

  final ShellTab current;
  final void Function(ShellTab tab) onSelect;
  final VoidCallback onSignOut;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final state = AppScope.of(context);
    final school = state.school;
    final student = state.student;
    final brand = brandOf(context);
    final white70 = Colors.white.withValues(alpha: 0.8);
    return Drawer(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            decoration: BoxDecoration(gradient: heroGradient(brand)),
            child: Stack(children: [
              const Positioned.fill(child: HeroDecoration()),
              SafeArea(
                bottom: false,
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(20, 20, 20, 20),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    const SchoolLogo(size: 56, onColor: true),
                    const SizedBox(height: 14),
                    Text(school.name,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: theme.textTheme.titleLarge?.copyWith(color: Colors.white)),
                    if (school.tagline != null)
                      Text(school.tagline!, style: theme.textTheme.bodyMedium?.copyWith(color: white70)),
                    const SizedBox(height: 18),
                    Container(
                      padding: const EdgeInsets.all(10),
                      decoration: BoxDecoration(
                        color: Colors.white.withValues(alpha: 0.14),
                        borderRadius: BorderRadius.circular(16),
                      ),
                      child: Row(children: [
                        InitialsAvatar(
                          name: student?.fullName ?? '',
                          size: 38,
                          background: Colors.white,
                          foreground: heroColors(brand).$1,
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                            Text(student?.fullName ?? '',
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: theme.textTheme.titleSmall?.copyWith(color: Colors.white)),
                            if ((student?.groupLabel ?? '').isNotEmpty)
                              Text(student!.groupLabel,
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: theme.textTheme.labelMedium?.copyWith(color: white70)),
                          ]),
                        ),
                      ]),
                    ),
                  ]),
                ),
              ),
            ]),
          ),
          Expanded(
            child: ListView(
              padding: const EdgeInsets.all(12),
              children: [
                for (final tab in ShellTab.values)
                  ValueListenableBuilder<int>(
                    valueListenable: state.unreadNotices,
                    builder: (context, unread, _) => ListTile(
                      selected: tab == current,
                      selectedTileColor: theme.colorScheme.primaryContainer.withValues(alpha: 0.35),
                      leading: Icon(tab == current ? tab.selectedIcon : tab.icon),
                      title: Text(tab.label),
                      trailing: tab == ShellTab.notices && unread > 0
                          ? Badge(label: Text('$unread'), backgroundColor: theme.colorScheme.primary)
                          : null,
                      onTap: () => onSelect(tab),
                    ),
                  ),
                const Padding(padding: EdgeInsets.symmetric(vertical: 8), child: Divider()),
                ListTile(
                  leading: const Icon(Icons.info_outline_rounded),
                  title: const Text('About this app'),
                  onTap: () => showAboutDialog(
                    context: context,
                    applicationName: '${school.displayName} Learning',
                    applicationVersion: AppConfig.appVersion,
                    applicationIcon: const SchoolLogo(size: 48),
                    children: const [
                      Text('Lessons, notes and notices from your school. Works on the campus Wi-Fi; '
                          'no internet connection is needed.'),
                    ],
                  ),
                ),
              ],
            ),
          ),
          SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
              child: OutlinedButton.icon(
                onPressed: onSignOut,
                icon: const Icon(Icons.logout_rounded),
                label: const Text('Sign out'),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
