import { NextRequest, NextResponse } from "next/server";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function GET(
  _request: NextRequest,
  context: { params: Promise<{ reviewId: string }> }
) {
  const { reviewId } = await context.params;
  if (!reviewId) {
    return NextResponse.json({ detail: "Missing review id" }, { status: 400 });
  }

  try {
    const res = await fetch(`${API_URL}/tabular/reviews/${reviewId}/export.xlsx`, {
      cache: "no-store",
    });

    if (!res.ok) {
      const text = await res.text();
      return NextResponse.json(
        { detail: text || res.statusText },
        { status: res.status }
      );
    }

    const blob = await res.arrayBuffer();
    const disposition =
      res.headers.get("Content-Disposition") ??
      `attachment; filename="tabular-review.xlsx"`;

    return new NextResponse(blob, {
      status: 200,
      headers: {
        "Content-Type":
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "Content-Disposition": disposition,
      },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Export failed";
    return NextResponse.json({ detail: message }, { status: 502 });
  }
}
