type AdminOnlyNoticeProps = {
  message: string;
};

export function AdminOnlyNotice({ message }: AdminOnlyNoticeProps) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-6 py-5 text-sm text-slate-600 shadow-sm">
      {message}
    </div>
  );
}
