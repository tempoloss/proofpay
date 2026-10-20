import { Board } from "./ui/board";
import { Hero } from "./ui/hero";
import { ForAgents, HowItWorks } from "./ui/sections";

export function HomePage() {
  return (
    <div className="space-y-28">
      <Hero />
      <HowItWorks />
      <Board />
      <ForAgents />
    </div>
  );
}
