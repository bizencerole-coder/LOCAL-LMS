import 'package:flutter/material.dart';

import '../api/models.dart';
import '../state/app_state.dart';
import '../widgets/brand.dart';
import '../widgets/layout.dart';
import '../widgets/notice_tile.dart';
import '../widgets/states.dart';

/// The Notices tab: everything the school posted for this student. Opening the tab
/// marks the notices as seen; the ones that were new keep their dot until it reloads.
class NoticesTab extends StatefulWidget {
  const NoticesTab({super.key, required this.active});

  /// The tab is showing (opening it marks the notices as seen).
  final bool active;

  @override
  State<NoticesTab> createState() => NoticesTabState();
}

class NoticesTabState extends State<NoticesTab> {
  final _loaderKey = GlobalKey<LoaderState<List<NoticeItem>>>();
  Set<String> _new = {};

  void reload() => _loaderKey.currentState?.reload();

  @override
  void didUpdateWidget(covariant NoticesTab oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.active && !oldWidget.active) reload();
  }

  Future<List<NoticeItem>> _load() async {
    final state = AppScope.read(context);
    final notices = await state.loadNotices();
    _new = {for (final notice in notices) if (state.isNoticeUnread(notice)) notice.id};
    if (widget.active) await state.markNoticesSeen(notices);
    return notices;
  }

  @override
  Widget build(BuildContext context) {
    final school = AppScope.of(context).school;
    return Loader<List<NoticeItem>>(
      key: _loaderKey,
      load: _load,
      builder: (context, notices, reload) => RefreshIndicator(
        onRefresh: reload,
        child: LayoutBuilder(
          builder: (context, constraints) => ListView(
            padding: readablePadding(constraints.maxWidth, maxWidth: 820, gutter: 20),
            children: [
              PageHeading(title: 'Notices', subtitle: 'From ${school.displayName}'),
              if (notices.isEmpty)
                const MessageView(
                  icon: Icons.notifications_none_rounded,
                  title: 'No notices',
                  message: 'Announcements from your school will appear here.',
                )
              else
                for (final notice in notices)
                  NoticeTile(
                    notice: notice,
                    unread: _new.contains(notice.id),
                    bodyLines: 3,
                    onTap: () => openNotice(context, notice),
                  ),
            ],
          ),
        ),
      ),
    );
  }
}

Future<void> openNotice(BuildContext context, NoticeItem notice) =>
    Navigator.of(context).push(MaterialPageRoute(builder: (_) => NoticeScreen(notice: notice)));

/// One notice in full.
class NoticeScreen extends StatelessWidget {
  const NoticeScreen({super.key, required this.notice});

  final NoticeItem notice;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('Notice')),
      body: LayoutBuilder(
        builder: (context, constraints) => ListView(
          padding: readablePadding(constraints.maxWidth, maxWidth: 760, gutter: 24),
          children: [
            Text(notice.title, style: theme.textTheme.headlineSmall),
            const SizedBox(height: 12),
            NoticeMeta(notice: notice, exactTime: true),
            const SizedBox(height: 20),
            const Divider(),
            const SizedBox(height: 20),
            SelectableText(
              notice.body ?? 'No further details.',
              style: theme.textTheme.bodyLarge?.copyWith(height: 1.55),
            ),
          ],
        ),
      ),
    );
  }
}
