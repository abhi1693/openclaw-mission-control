export function AdminOnlyNotice({ message }: { message: string }) {
  return (
    <div className="surface-card rounded-xl px-6 py-5 text-sm text-muted">
      {message}
    </div>
  );
}
