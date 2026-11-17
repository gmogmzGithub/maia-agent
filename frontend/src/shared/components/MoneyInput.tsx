"use client";
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type InputHTMLAttributes,
} from "react";
import {
  formatMoneyInput,
  moneyCaret,
  parseMoneyInput,
} from "@/shared/lib/money-input";

type Props = Omit<
  InputHTMLAttributes<HTMLInputElement>,
  "value" | "defaultValue" | "type" | "onChange" | "step"
> & {
  value?: string | number | null;
  defaultValue?: string | number | null;
  onValueChange?: (raw: string) => void;
  currency?: string | null;
};

export default function MoneyInput({
  value,
  defaultValue,
  name,
  min = 0,
  max,
  onValueChange,
  currency = "MXN",
  ...props
}: Props) {
  const [raw, setRaw] = useState(String(value ?? defaultValue ?? ""));
  const [edit, setEdit] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const caret = useRef<number | null>(null);
  useEffect(() => {
    if (value === undefined) return;
    setRaw((previous) => {
      const next = String(value ?? "");
      // Keep a decimal point or trailing zero while the parent stores a number.
      return next !== "" && previous !== "" && Number(previous) === Number(next)
        ? previous
        : next;
    });
  }, [value]);
  const display = formatMoneyInput(raw);
  useLayoutEffect(() => {
    const element = input.current;
    if (!element) return;
    let error = "";
    if (raw !== "" && !Number.isFinite(Number(raw)))
      error = "Escribe un monto válido.";
    else if (raw !== "" && Number(raw) < Number(min))
      error = `El monto mínimo es ${formatMoneyInput(String(min))}.`;
    else if (raw !== "" && max !== undefined && Number(raw) > Number(max))
      error = `El monto máximo es ${formatMoneyInput(String(max))}.`;
    element.setCustomValidity(error);
    if (caret.current !== null && document.activeElement === element) {
      const position = moneyCaret(display, caret.current);
      element.setSelectionRange(position, position);
    }
    caret.current = null;
  }, [raw, display, min, max, edit]);
  useEffect(() => {
    if (value !== undefined) return;
    const form = input.current?.form;
    const reset = () => setRaw(String(defaultValue ?? ""));
    form?.addEventListener("reset", reset);
    return () => form?.removeEventListener("reset", reset);
  }, [value, defaultValue]);
  return (
    <>
      {name && (
        <input
          type="hidden"
          name={name}
          value={raw}
          disabled={props.disabled}
        />
      )}
      <span className="money-input">
        <span className="money-input-prefix" aria-hidden="true">
          {currency === "USD" ? "US$" : currency === "MXN" ? "MX$" : "$"}
        </span>
        <input
          {...props}
          data-feedback-field={name}
          aria-description={
            currency === "USD"
              ? "Dólares estadounidenses"
              : currency === "MXN"
                ? "Pesos mexicanos"
                : "Importe monetario"
          }
          ref={input}
          type="text"
          inputMode="decimal"
          value={display}
          onChange={(event) => {
            const next = parseMoneyInput(event.target.value);
            if (next === null) return;
            caret.current = event.target.value
              .slice(
                0,
                event.target.selectionStart ?? event.target.value.length,
              )
              .replace(/[,\s]/g, "").length;
            if (event.target.value.replace(/[,\s]/g, "").startsWith("."))
              caret.current++;
            setRaw(next);
            setEdit((version) => version + 1);
            onValueChange?.(next);
          }}
        />
      </span>
    </>
  );
}
