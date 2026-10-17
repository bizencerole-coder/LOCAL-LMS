import 'dart:async';

import 'package:flutter/material.dart';

import '../api/models.dart';
import '../state/app_state.dart';
import '../theme.dart';
import 'brand.dart';

/// The banner at the top of the home page: slides staff post on the dashboard, moving
/// on every [interval] (not when the tablet asks for less motion), with dots below.
class BannerCarousel extends StatefulWidget {
  const BannerCarousel({
    super.key,
    required this.banners,
    required this.onOpen,
    this.interval = const Duration(seconds: 6),
  });

  final List<BannerItem> banners;
  final void Function(BannerItem banner) onOpen;
  final Duration interval;

  /// Slide height for a width: about 8:3, within limits that keep the text room.
  static double heightFor(BuildContext context, double width) {
    final textScale = MediaQuery.textScalerOf(context).scale(1);
    final minimum = 168 + (textScale - 1).clamp(0, 2) * 90;
    return (width * 0.36).clamp(minimum, 230).toDouble();
  }

  @override
  State<BannerCarousel> createState() => _BannerCarouselState();
}

class _BannerCarouselState extends State<BannerCarousel> {
  final _controller = PageController();
  Timer? _timer;
  int _page = 0;

  @override
  void initState() {
    super.initState();
    _restart();
  }

  @override
  void didUpdateWidget(covariant BannerCarousel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.banners.length != widget.banners.length) {
      if (_page >= widget.banners.length) {
        _page = 0;
        if (_controller.hasClients) _controller.jumpToPage(0);
      }
      _restart();
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    _controller.dispose();
    super.dispose();
  }

  void _restart() {
    _timer?.cancel();
    if (widget.banners.length < 2) return;
    _timer = Timer.periodic(widget.interval, (_) => _advance());
  }

  void _advance() {
    if (!mounted || !_controller.hasClients || widget.banners.length < 2) return;
    if (MediaQuery.disableAnimationsOf(context)) return;
    final next = (_page + 1) % widget.banners.length;
    _controller.animateToPage(next, duration: const Duration(milliseconds: 520), curve: Curves.easeOutCubic);
  }

  @override
  Widget build(BuildContext context) {
    final banners = widget.banners;
    if (banners.isEmpty) return const SizedBox.shrink();
    return LayoutBuilder(
      builder: (context, constraints) {
        final height = BannerCarousel.heightFor(context, constraints.maxWidth);
        return Column(
          children: [
            SizedBox(
              height: height,
              child: NotificationListener<ScrollStartNotification>(
                // A swipe by the student restarts the countdown.
                onNotification: (notification) {
                  if (notification.dragDetails != null) _restart();
                  return false;
                },
                child: PageView.builder(
                  controller: _controller,
                  itemCount: banners.length,
                  onPageChanged: (page) => setState(() => _page = page),
                  itemBuilder: (context, i) => Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 2),
                    child: BannerSlide(
                      banner: banners[i],
                      onTap: banners[i].link == null ? null : () => widget.onOpen(banners[i]),
                    ),
                  ),
                ),
              ),
            ),
            if (banners.length > 1) ...[
              const SizedBox(height: 12),
              _Dots(count: banners.length, current: _page),
            ],
          ],
        );
      },
    );
  }
}

/// One slide: the picture (or the school colour) with its title and subtitle.
class BannerSlide extends StatelessWidget {
  const BannerSlide({super.key, required this.banner, this.onTap});

  final BannerItem banner;
  final VoidCallback? onTap;

  static String openLabel(BannerLink link) => switch (link.type) {
        BannerLinkType.notice => 'Read notice',
        BannerLinkType.subject => 'Open subject',
        BannerLinkType.module => 'Open module',
      };

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final brand = brandOf(context);
    final url = banner.imageUrl;
    final link = banner.link;
    return Semantics(
      button: onTap != null,
      label: [banner.title, banner.subtitle].nonNulls.join('. '),
      excludeSemantics: true,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(22),
        child: Material(
          color: Colors.transparent,
          child: Ink(
            decoration: BoxDecoration(gradient: heroGradient(brand)),
            child: InkWell(
              onTap: onTap,
              child: Stack(
                fit: StackFit.expand,
                children: [
                  if (url == null)
                    const HeroDecoration()
                  else ...[
                    Image.network(
                      AppScope.of(context).api.resolve(url).toString(),
                      fit: BoxFit.cover,
                      errorBuilder: (_, _, _) => const HeroDecoration(),
                      frameBuilder: (context, child, frame, synchronous) => AnimatedOpacity(
                        opacity: synchronous || frame != null ? 1 : 0,
                        duration: const Duration(milliseconds: 300),
                        child: child,
                      ),
                    ),
                    // Keeps white text readable on any picture.
                    const DecoratedBox(
                      decoration: BoxDecoration(
                        gradient: LinearGradient(
                          begin: Alignment.centerLeft,
                          end: Alignment.centerRight,
                          colors: [Color(0xB3000000), Color(0x40000000), Color(0x00000000)],
                          stops: [0, 0.6, 1],
                        ),
                      ),
                    ),
                  ],
                  Padding(
                    padding: const EdgeInsets.fromLTRB(24, 18, 24, 18),
                    child: Align(
                      alignment: Alignment.centerLeft,
                      child: ConstrainedBox(
                        constraints: const BoxConstraints(maxWidth: 560),
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              banner.title,
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                              style: theme.textTheme.headlineSmall?.copyWith(color: Colors.white, height: 1.15),
                            ),
                            if (banner.subtitle != null) ...[
                              const SizedBox(height: 6),
                              Text(
                                banner.subtitle!,
                                maxLines: 2,
                                overflow: TextOverflow.ellipsis,
                                style: theme.textTheme.bodyLarge?.copyWith(color: Colors.white.withValues(alpha: 0.88)),
                              ),
                            ],
                            if (link != null) ...[
                              const SizedBox(height: 14),
                              Container(
                                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 7),
                                decoration: BoxDecoration(
                                  color: Colors.white.withValues(alpha: 0.18),
                                  borderRadius: BorderRadius.circular(999),
                                  border: Border.all(color: Colors.white.withValues(alpha: 0.35)),
                                ),
                                child: Row(mainAxisSize: MainAxisSize.min, children: [
                                  Text(openLabel(link),
                                      style: theme.textTheme.labelLarge?.copyWith(color: Colors.white)),
                                  const SizedBox(width: 4),
                                  const Icon(Icons.arrow_forward_rounded, size: 16, color: Colors.white),
                                ]),
                              ),
                            ],
                          ],
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _Dots extends StatelessWidget {
  const _Dots({required this.count, required this.current});

  final int count;
  final int current;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Semantics(
      label: 'Slide ${current + 1} of $count',
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          for (var i = 0; i < count; i++)
            AnimatedContainer(
              duration: const Duration(milliseconds: 250),
              margin: const EdgeInsets.symmetric(horizontal: 3),
              width: i == current ? 22 : 8,
              height: 8,
              decoration: BoxDecoration(
                color: i == current ? scheme.primary : scheme.outlineVariant,
                borderRadius: BorderRadius.circular(4),
              ),
            ),
        ],
      ),
    );
  }
}
