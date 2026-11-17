// Render emphasis as text elements, never customer-supplied HTML.
export default function MessageText({ text }: { text: string }) {
  return (
    <p>
      {text.split(/(\*\*[^*\n]+\*\*|\*[^*\n]+\*)/g).map((part, index) => {
        if (part.startsWith("**") && part.endsWith("**"))
          return <strong key={index}>{part.slice(2, -2)}</strong>;
        if (part.startsWith("*") && part.endsWith("*"))
          return <strong key={index}>{part.slice(1, -1)}</strong>;
        return part;
      })}
    </p>
  );
}
