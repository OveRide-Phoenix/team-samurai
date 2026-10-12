const { Font } = require("@pdf-lib/standard-fonts/lib/Font.js");

module.exports = (name) => {
  const source = Font.load(name);
  return {
    name,
    bbox: source.FontBBox,
    ascender: source.Ascender,
    descender: source.Descender,
    xHeight: source.XHeight,
    capHeight: source.CapHeight,
    glyphNames: source.CharMetrics.map((metric) => metric.N).join(" "),
    glyphWidths: source.CharMetrics.map((metric) => metric.WX),
    kernPairs: [],
  };
};
