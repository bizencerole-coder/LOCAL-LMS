import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../state/app_state.dart';
import '../widgets/states.dart';

const _cantShow = 'This image could not be shown. The file may be damaged; please tell your teacher.';

/// Decoded images are kept within this many pixels per side: enough to zoom into
/// a photo of a whiteboard, and within what tablet GPUs can draw in one piece.
const _maxImageSide = 4096;

/// Shows an image with pinch zoom (and double-tap zoom). Like notes, the file is
/// downloaded once; opening it is what the server records.
class ImageViewerScreen extends StatefulWidget {
  const ImageViewerScreen({super.key, required this.contentId, required this.title});

  final String contentId;
  final String title;

  @override
  State<ImageViewerScreen> createState() => _ImageViewerScreenState();
}

class _ImageViewerScreenState extends State<ImageViewerScreen> {
  late final ApiClient _api;
  final _transform = TransformationController();
  ImageProvider? _image;
  ApiException? _error;
  double? _progress;
  Offset? _doubleTapAt;

  /// Incremented on every (re)load and on dispose, so a slow load that finishes
  /// after the student retried or left is discarded.
  int _generation = 0;

  @override
  void initState() {
    super.initState();
    _api = AppScope.read(context).api;
    _load();
  }

  @override
  void dispose() {
    _generation++;
    _image?.evict().ignore(); // do not keep the decoded picture in memory after leaving
    _transform.dispose();
    super.dispose();
  }

  /// Also "Try again": opening the item again gets a fresh signed URL.
  Future<void> _load() async {
    final generation = ++_generation;
    if (_error != null || _image != null) {
      _image?.evict().ignore();
      _transform.value = Matrix4.identity();
      setState(() {
        _image = null;
        _error = null;
        _progress = null;
      });
    }
    try {
      final file = await _api.fetchContentFile(widget.contentId, onProgress: (received, total) {
        if (!mounted || generation != _generation || total == null || total <= 0) return;
        final progress = received / total;
        if (progress - (_progress ?? 0) >= 0.02 || progress >= 1) setState(() => _progress = progress);
      });
      if (!mounted || generation != _generation) return;
      setState(() => _image = ResizeImage(
            MemoryImage(file.bytes),
            width: _maxImageSide,
            height: _maxImageSide,
            policy: ResizeImagePolicy.fit,
          ));
    } on ApiException catch (e) {
      if (mounted && generation == _generation) setState(() => _error = e);
    } catch (_) {
      if (mounted && generation == _generation) {
        setState(() => _error = const ApiException(ApiErrorKind.invalid, _cantShow));
      }
    }
  }

  /// A file that downloaded but does not decode shows the same error screen as a failed download.
  Widget _decodeFailed(ImageProvider image) {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted && identical(_image, image) && _error == null) {
        setState(() => _error = const ApiException(ApiErrorKind.invalid, _cantShow));
      }
    });
    return const SizedBox.shrink();
  }

  void _toggleZoom() {
    if (_transform.value.getMaxScaleOnAxis() > 1.01) {
      _transform.value = Matrix4.identity();
      return;
    }
    const scale = 2.5;
    final at = _doubleTapAt ?? Offset.zero;
    _transform.value = Matrix4.diagonal3Values(scale, scale, 1)
      ..setTranslationRaw(-at.dx * (scale - 1), -at.dy * (scale - 1), 0);
  }

  Widget _body() {
    final error = _error;
    if (error != null) return ErrorView(error: error, onRetry: _load);
    final image = _image;
    if (image == null) return LoadingView(message: 'Opening image…', progress: _progress);

    return GestureDetector(
      onDoubleTapDown: (details) => _doubleTapAt = details.localPosition,
      onDoubleTap: _toggleZoom,
      child: InteractiveViewer(
        transformationController: _transform,
        minScale: 1,
        maxScale: 8,
        child: SizedBox.expand(
          child: Image(
            image: image,
            fit: BoxFit.contain,
            gaplessPlayback: true,
            filterQuality: FilterQuality.medium,
            semanticLabel: widget.title,
            frameBuilder: (context, child, frame, wasSynchronouslyLoaded) => frame == null && !wasSynchronouslyLoaded
                ? const Center(child: CircularProgressIndicator(color: Colors.white))
                : child,
            errorBuilder: (context, error, stackTrace) => _decodeFailed(image),
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.title)),
      backgroundColor: _image != null && _error == null ? Colors.black : null,
      body: _body(),
    );
  }
}
