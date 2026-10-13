use std::time::{Duration, Instant};

/// Initial one-RPV scheduler deliberately has one browser/PDF/OCR lane.
/// It never increases load automatically. Slow responses add inter-call delay.
pub struct ResourceGovernor {
    failures: u8,
    open_until: Option<Instant>,
    pub mean_duration_ms: u64,
    samples: u64,
}
impl Default for ResourceGovernor {
    fn default() -> Self {
        Self {
            failures: 0,
            open_until: None,
            mean_duration_ms: 0,
            samples: 0,
        }
    }
}
impl ResourceGovernor {
    pub fn allow(&mut self, now: Instant) -> bool {
        match self.open_until {
            Some(until) if now < until => false,
            Some(_) => {
                self.open_until = None;
                self.failures = 0;
                true
            }
            None => true,
        }
    }
    pub fn record(&mut self, elapsed: Duration, success: bool, now: Instant) {
        self.samples += 1;
        self.mean_duration_ms = ((self.mean_duration_ms as u128 * (self.samples - 1) as u128
            + elapsed.as_millis())
            / self.samples as u128) as u64;
        if success {
            self.failures = 0;
        } else {
            self.failures += 1;
            if self.failures >= 3 {
                self.open_until = Some(now + Duration::from_secs(30));
            }
        }
    }
    pub fn spacing(&self) -> Duration {
        Duration::from_millis(if self.mean_duration_ms > 5000 {
            1000
        } else {
            0
        })
    }
    pub fn backoff(attempt: u32) -> Duration {
        Duration::from_millis(250 * 2u64.pow(attempt.min(5)))
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn breaker_and_backoff() {
        let mut g = ResourceGovernor::default();
        let now = Instant::now();
        for _ in 0..3 {
            g.record(Duration::from_secs(7), false, now);
        }
        assert!(!g.allow(now));
        assert!(g.allow(now + Duration::from_secs(31)));
        assert_eq!(g.spacing(), Duration::from_secs(1));
        assert!(ResourceGovernor::backoff(2) > ResourceGovernor::backoff(1));
    }
}
