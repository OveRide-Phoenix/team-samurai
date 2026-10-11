export function GET(): Response {
  return Response.json({ status: "ok", service: "samurai-frontend" });
}
