import { cn } from "@/lib/utils";

type Props = {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
  className?: string;
};

export function PageHeader({ title, subtitle, actions, className }: Props) {
  return (
    <div className={cn("mb-6 flex flex-wrap items-start justify-between gap-4", className)}>
      <div>
        <h1
          className="font-serif text-2xl"
          style={{ fontFamily: "var(--font-garamond), serif" }}
        >
          {title}
        </h1>
        {subtitle && <p className="mt-1 text-sm text-neutral-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
