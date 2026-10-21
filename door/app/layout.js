export const metadata = { title: "Marc" };

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body style={{ margin: 0, background: "#000", color: "#f5f5f7" }}>{children}</body>
    </html>
  );
}
