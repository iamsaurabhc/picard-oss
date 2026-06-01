import { AppSidebar } from "@/components/app-sidebar";

export default function ChatLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen">
      <AppSidebar />
      <main className="flex flex-1 flex-col overflow-hidden">{children}</main>
    </div>
  );
}
