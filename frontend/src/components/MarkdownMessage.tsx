import { Suspense, lazy } from "react";

const MarkdownRenderer = lazy(() => import("./MarkdownRenderer"));

interface MarkdownMessageProps {
  content: string;
  className?: string;
}

function PlainTextFallback({ content, className }: MarkdownMessageProps) {
  return (
    <div className={className}>
      {content.split(/\n{2,}/).map((paragraph, index) => (
        <p key={`${index}:${paragraph.slice(0, 12)}`} className="whitespace-pre-wrap break-words">
          {paragraph}
        </p>
      ))}
    </div>
  );
}

export default function MarkdownMessage({ content, className }: MarkdownMessageProps) {
  return (
    <Suspense fallback={<PlainTextFallback content={content} className={className} />}>
      <MarkdownRenderer content={content} className={className} />
    </Suspense>
  );
}
