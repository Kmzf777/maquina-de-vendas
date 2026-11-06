// Célula "Passou por" (F5): os canais do lead na ordem, com as datas no tooltip.
import { passouPorTexto, passouPorTooltip, type Jornada } from "@/lib/traffic-jornada";

export function PassouPor({ jornada }: { jornada?: Jornada | null }) {
  const estimado = !jornada || jornada.estimado;
  return (
    <span title={passouPorTooltip(jornada)} className={estimado ? "text-[#b5b1aa]" : "text-[#7b7b78]"}>
      {passouPorTexto(jornada)}
    </span>
  );
}
