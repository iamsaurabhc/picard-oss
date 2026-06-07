"use client";

import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";
import type { ChatReference } from "@/lib/picardApi";
import { cn } from "@/lib/utils";

const MARKER = /\[(\d+)\]/g;

type Segment =
  | { type: "text"; content: string }
  | { type: "citation"; index: number };

function splitSegments(text: string): Segment[] {
  const segments: Segment[] = [];
  let last = 0;
  let match: RegExpExecArray | null;
  const re = new RegExp(MARKER.source, "g");
  while ((match = re.exec(text)) !== null) {
    if (match.index > last) {
      segments.push({ type: "text", content: text.slice(last, match.index) });
    }
    segments.push({ type: "citation", index: parseInt(match[1], 10) });
    last = match.index + match[0].length;
  }
  if (last < text.length) {
    segments.push({ type: "text", content: text.slice(last) });
  }
  return segments;
}

function claimTextForCitation(segments: Segment[], citeSegmentIndex: number): string {
  const parts: string[] = [];
  for (let i = citeSegmentIndex - 1; i >= 0; i--) {
    const seg = segments[i];
    if (seg.type !== "text") break;
    parts.unshift(seg.content);
    if (/[.!?]\s*$/.test(seg.content)) break;
  }
  return parts.join("").replace(/\[\d+\]/g, "").trim();
}

function CitationButton({
  index,
  reference,
  claimText,
  onCitationClick,
}: {
  index: number;
  reference?: ChatReference;
  claimText: string;
  onCitationClick?: (ref: ChatReference, claimText?: string) => void;
}) {
  return (
    <button
      type="button"
      className="mx-0.5 inline rounded bg-neutral-200 px-1.5 py-0.5 text-xs font-medium text-neutral-800 hover:bg-neutral-300 align-baseline"
      onClick={() => reference && onCitationClick?.(reference, claimText)}
    >
      [{index}]
    </button>
  );
}

function renderInlineCitations(
  text: string,
  byIndex: Map<number, ChatReference>,
  onCitationClick?: (ref: ChatReference, claimText?: string) => void,
  keyPrefix = ""
): React.ReactNode {
  const segments = splitSegments(text);
  if (segments.length === 1 && segments[0].type === "text") {
    return text;
  }
  return segments.map((seg, i) => {
    if (seg.type === "citation") {
      return (
        <CitationButton
          key={`${keyPrefix}-cite-${i}-${seg.index}`}
          index={seg.index}
          reference={byIndex.get(seg.index)}
          claimText={claimTextForCitation(segments, i)}
          onCitationClick={onCitationClick}
        />
      );
    }
    return <React.Fragment key={`${keyPrefix}-text-${i}`}>{seg.content}</React.Fragment>;
  });
}

function injectCitations(
  children: React.ReactNode,
  byIndex: Map<number, ChatReference>,
  onCitationClick?: (ref: ChatReference, claimText?: string) => void,
  keyPrefix = ""
): React.ReactNode {
  if (children == null) return children;
  if (typeof children === "string") {
    return renderInlineCitations(children, byIndex, onCitationClick, keyPrefix);
  }
  if (Array.isArray(children)) {
    return children.map((child, i) => {
      const prefix = `${keyPrefix}-${i}`;
      if (typeof child === "string") {
        return (
          <React.Fragment key={prefix}>
            {renderInlineCitations(child, byIndex, onCitationClick, prefix)}
          </React.Fragment>
        );
      }
      if (React.isValidElement<{ children?: React.ReactNode }>(child)) {
        return React.cloneElement(child, {
          key: child.key ?? prefix,
          children: injectCitations(child.props.children, byIndex, onCitationClick, prefix),
        });
      }
      return child;
    });
  }
  if (React.isValidElement<{ children?: React.ReactNode }>(children)) {
    return React.cloneElement(children, {
      children: injectCitations(children.props.children, byIndex, onCitationClick, keyPrefix),
    });
  }
  return children;
}

function makeCitationComponents(
  byIndex: Map<number, ChatReference>,
  onCitationClick?: (ref: ChatReference, claimText?: string) => void
): Components {
  const wrap = (
    Tag: "p" | "li" | "h1" | "h2" | "h3" | "h4" | "h5" | "h6" | "td" | "th" | "blockquote" | "strong" | "em"
  ) =>
    ({ children, ...props }: { children?: React.ReactNode }) => {
      const El = Tag;
      return <El {...props}>{injectCitations(children, byIndex, onCitationClick)}</El>;
    };

  return {
    p: wrap("p"),
    li: wrap("li"),
    h1: wrap("h1"),
    h2: wrap("h2"),
    h3: wrap("h3"),
    h4: wrap("h4"),
    h5: wrap("h5"),
    h6: wrap("h6"),
    td: wrap("td"),
    th: wrap("th"),
    blockquote: wrap("blockquote"),
    strong: wrap("strong"),
    em: wrap("em"),
  };
}

type Props = {
  text: string;
  references?: ChatReference[];
  onCitationClick?: (ref: ChatReference, claimText?: string) => void;
  className?: string;
};

export function MarkdownWithCitations({
  text,
  references = [],
  onCitationClick,
  className,
}: Props) {
  const byIndex = new Map(references.map((r) => [r.index, r]));
  const components = React.useMemo(
    () => makeCitationComponents(byIndex, onCitationClick),
    [byIndex, onCitationClick]
  );

  return (
    <div className={cn("prose-picard", className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {text}
      </ReactMarkdown>
    </div>
  );
}
