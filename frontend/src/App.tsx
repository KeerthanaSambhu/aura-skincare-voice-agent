import { MotionConfig } from "motion/react";
import { Footer } from "./components/layout/Footer";
import { Nav } from "./components/layout/Nav";
import { SmoothScroll } from "./components/providers/SmoothScroll";
import { CallSummary } from "./components/sections/CallSummary";
import { Hero } from "./components/sections/Hero";
import { HowItWorks } from "./components/sections/HowItWorks";
import { TestOrders } from "./components/sections/TestOrders";
import { VoiceConsole } from "./components/sections/VoiceConsole";
import { useVoiceCall } from "./voice/useVoiceCall";

export default function App() {
  const call = useVoiceCall();

  return (
    // reducedMotion="user": Motion drops transform animations for visitors who prefer reduced motion.
    <MotionConfig reducedMotion="user">
      <SmoothScroll>
        <Nav />
        <main>
          <Hero />
          <VoiceConsole
            amplitude={call.amplitude}
            error={call.error}
            hasRecord={call.savingRecord || call.record !== null}
            onEnd={call.end}
            onStart={call.start}
            state={call.state}
            step={call.step}
            transcript={call.transcript}
          />
          <TestOrders />
          <HowItWorks />
          <CallSummary
            localTranscript={call.transcript}
            record={call.record}
            recordError={call.recordError}
            saving={call.savingRecord}
          />
        </main>
        <Footer />
      </SmoothScroll>
    </MotionConfig>
  );
}
