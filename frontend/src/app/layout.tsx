import { ErrorFeedbackProvider } from "@/shared/components/ErrorFeedback";
import type { Metadata } from "next";
import "@/shared/styles/globals.css";

export const metadata: Metadata = {
  title: {
    default: "Maia · Un lugar para tu siguiente etapa",
    template: "%s · Maia",
  },
  description:
    "Encuentra propiedades en venta y renta en Guadalajara, Zapopan, Tlaquepaque y Tonalá. Cuéntanos qué buscas.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="es-MX">
      <body>
        <ErrorFeedbackProvider>{children}</ErrorFeedbackProvider>
      </body>
    </html>
  );
}
