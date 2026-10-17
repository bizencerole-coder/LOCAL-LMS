import 'dart:math' as math;

import 'package:flutter/widgets.dart';

/// Height of [lines] lines of [style] at the student's text size, for cards that need a
/// fixed height (grid cells, horizontal rows). Measured per style because Android 14+
/// enlarges big text less than small text.
double textLinesHeight(BuildContext context, TextStyle? style, [int lines = 1]) {
  final fontSize = style?.fontSize ?? 14;
  return lines * MediaQuery.textScalerOf(context).scale(fontSize) * (style?.height ?? 1.3);
}

/// Lists on wide tablets stay readable: their content is centred in a column at most
/// this wide (in logical pixels; a 10" tablet in landscape is about 1200–1300 wide).
const readableWidth = 1040.0;

/// Padding that centres a list's content in a column at most [maxWidth] wide, with at
/// least [gutter] on every side. The whole width still scrolls and pulls to refresh.
EdgeInsets readablePadding(double availableWidth, {double maxWidth = readableWidth, double gutter = 24}) {
  final side = math.max(gutter, (availableWidth - maxWidth) / 2);
  return EdgeInsets.fromLTRB(side, gutter, side, gutter);
}
