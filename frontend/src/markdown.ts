import MarkdownIt from "markdown-it";
import DOMPurify from "dompurify";

const renderer = new MarkdownIt({ html: true, linkify: false, breaks: false });
export function renderMarkdown(value: string) {
  return DOMPurify.sanitize(renderer.render(value), {
    ALLOWED_TAGS: [
      "p",
      "h1",
      "h2",
      "h3",
      "h4",
      "h5",
      "h6",
      "a",
      "blockquote",
      "ul",
      "ol",
      "li",
      "pre",
      "code",
      "em",
      "strong",
      "del",
      "s",
      "hr",
      "br",
      "table",
      "thead",
      "tbody",
      "tfoot",
      "tr",
      "td",
      "th",
      "caption",
      "colgroup",
      "col",
      "span",
      "div",
      "sup",
      "sub",
    ],
    ALLOWED_ATTR: ["href", "title", "colspan", "rowspan", "align", "start"],
    ALLOW_DATA_ATTR: false,
  });
}
