export interface XmlNode {
  name: string;
  attrs: Record<string, string>;
  children: XmlNode[];
  text: string;
}

const NAMED_ENTITIES: Record<string, string> = {
  amp: "&",
  lt: "<",
  gt: ">",
  quot: '"',
  apos: "'",
};

function decodeEntities(input: string): string {
  if (!input.includes("&")) {
    return input;
  }
  return input.replace(/&(#x?[0-9a-fA-F]+|[a-zA-Z]+);/g, (whole, body: string) => {
    if (body.startsWith("#x") || body.startsWith("#X")) {
      const code = Number.parseInt(body.slice(2), 16);
      return Number.isNaN(code) ? whole : safeFromCodePoint(code);
    }
    if (body.startsWith("#")) {
      const code = Number.parseInt(body.slice(1), 10);
      return Number.isNaN(code) ? whole : safeFromCodePoint(code);
    }
    const mapped = NAMED_ENTITIES[body];
    return mapped ?? whole;
  });
}

function safeFromCodePoint(code: number): string {
  if (code < 0 || code > 0x10ffff) {
    return "";
  }
  try {
    return String.fromCodePoint(code);
  } catch {
    return "";
  }
}

class XmlReader {
  private readonly src: string;
  private i = 0;

  constructor(src: string) {
    this.src = src;
  }

  parseDocument(): XmlNode {
    const root = this.readContentUntilRoot();
    this.skipTrailingMisc();
    return root;
  }

  private eof(): boolean {
    return this.i >= this.src.length;
  }

  private fail(message: string): never {
    throw new Error(`Malformed XML: ${message} (at offset ${this.i})`);
  }

  private skipWhitespace(): void {
    while (!this.eof() && /\s/.test(this.src[this.i] ?? "")) {
      this.i += 1;
    }
  }

  private startsWith(token: string): boolean {
    return this.src.startsWith(token, this.i);
  }

  private skipMisc(): boolean {
    this.skipWhitespace();
    if (this.startsWith("<!--")) {
      const end = this.src.indexOf("-->", this.i + 4);
      if (end < 0) {
        this.fail("unterminated comment");
      }
      this.i = end + 3;
      return true;
    }
    if (this.startsWith("<?")) {
      const end = this.src.indexOf("?>", this.i + 2);
      if (end < 0) {
        this.fail("unterminated processing instruction");
      }
      this.i = end + 2;
      return true;
    }
    if (this.startsWith("<!DOCTYPE") || this.startsWith("<!doctype")) {
      this.i = this.skipDoctype();
      return true;
    }
    return false;
  }

  private skipDoctype(): number {
    let depth = 0;
    let j = this.i + 2;
    while (j < this.src.length) {
      const ch = this.src[j];
      if (ch === "[") {
        depth += 1;
      } else if (ch === "]") {
        depth -= 1;
      } else if (ch === ">" && depth <= 0) {
        return j + 1;
      }
      j += 1;
    }
    return this.fail("unterminated DOCTYPE");
  }

  private skipTrailingMisc(): void {
    while (this.skipMisc()) {
      // consume all trailing comments / PIs
    }
    this.skipWhitespace();
    if (!this.eof()) {
      this.fail("trailing content after root element");
    }
  }

  private readContentUntilRoot(): XmlNode {
    while (this.skipMisc()) {
      // skip prolog misc items
    }
    this.skipWhitespace();
    if (this.eof() || this.src[this.i] !== "<") {
      this.fail("missing root element");
    }
    return this.readElement();
  }

  private readName(): string {
    const start = this.i;
    while (!this.eof()) {
      const ch = this.src[this.i] ?? "";
      if (/[\s/>=?!]/.test(ch)) {
        break;
      }
      this.i += 1;
    }
    const name = this.src.slice(start, this.i);
    if (name.length === 0) {
      this.fail("empty name");
    }
    return name;
  }

  private readAttributes(node: XmlNode): void {
    for (;;) {
      this.skipWhitespace();
      const ch = this.src[this.i];
      if (ch === ">" || ch === "/") {
        return;
      }
      if (ch === undefined) {
        this.fail("unexpected end in attributes");
      }
      const name = this.readName();
      this.skipWhitespace();
      if (this.src[this.i] !== "=") {
        node.attrs[name] = "";
        continue;
      }
      this.i += 1;
      this.skipWhitespace();
      node.attrs[name] = this.readAttrValue();
    }
  }

  private readAttrValue(): string {
    const quote = this.src[this.i];
    if (quote !== '"' && quote !== "'") {
      this.fail("attribute value must be quoted");
    }
    const start = this.i + 1;
    const end = this.src.indexOf(quote, start);
    if (end < 0) {
      this.fail("unterminated attribute value");
    }
    this.i = end + 1;
    return decodeEntities(this.src.slice(start, end));
  }

  private readElement(): XmlNode {
    if (this.src[this.i] !== "<") {
      this.fail("expected '<'");
    }
    this.i += 1;
    const name = this.readName();
    const node: XmlNode = { name, attrs: {}, children: [], text: "" };
    this.readAttributes(node);
    this.skipWhitespace();
    if (this.startsWith("/>")) {
      this.i += 2;
      return node;
    }
    if (this.src[this.i] !== ">") {
      this.fail("expected '>' or '/>'");
    }
    this.i += 1;
    this.readChildren(node, name);
    return node;
  }

  private readChildren(node: XmlNode, openName: string): void {
    let textRun = "";
    const flush = (): void => {
      if (textRun.length > 0) {
        node.text += decodeEntities(textRun);
        textRun = "";
      }
    };
    for (;;) {
      if (this.eof()) {
        this.fail(`unclosed element <${openName}>`);
      }
      if (this.startsWith("</")) {
        flush();
        this.i += 2;
        const closeName = this.readName();
        this.skipWhitespace();
        if (this.src[this.i] !== ">") {
          this.fail(`malformed end tag </${closeName}>`);
        }
        this.i += 1;
        if (closeName !== openName) {
          this.fail(`mismatched end tag </${closeName}> for <${openName}>`);
        }
        return;
      }
      if (this.startsWith("<!--")) {
        flush();
        const end = this.src.indexOf("-->", this.i + 4);
        if (end < 0) {
          this.fail("unterminated comment");
        }
        this.i = end + 3;
        continue;
      }
      if (this.startsWith("<![CDATA[")) {
        flush();
        const end = this.src.indexOf("]]>", this.i + 9);
        if (end < 0) {
          this.fail("unterminated CDATA");
        }
        node.text += this.src.slice(this.i + 9, end);
        this.i = end + 3;
        continue;
      }
      if (this.src[this.i] === "<") {
        flush();
        node.children.push(this.readElement());
        continue;
      }
      textRun += this.src[this.i];
      this.i += 1;
    }
  }
}

export function parseXml(input: string): XmlNode {
  return new XmlReader(input).parseDocument();
}

export function findAll(node: XmlNode, name: string): XmlNode[] {
  const out: XmlNode[] = [];
  const stack: XmlNode[] = [...node.children];
  while (stack.length > 0) {
    const current = stack.shift();
    if (current === undefined) {
      continue;
    }
    if (current.name === name) {
      out.push(current);
    }
    for (const child of current.children) {
      stack.unshift(child);
    }
  }
  return out;
}

export function textOf(node: XmlNode | undefined): string {
  if (node === undefined) {
    return "";
  }
  let result = node.text;
  for (const child of node.children) {
    result += textOf(child);
  }
  return result;
}
