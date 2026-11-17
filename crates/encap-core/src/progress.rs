//! Operation-scoped progress, forwarded from borrowed native callback buffers.
use serde_json::Value;
use std::{cell::RefCell, sync::Arc};
pub type ProgressHandler = Arc<dyn Fn(Value) + Send + Sync>;
thread_local! {static HANDLER: RefCell<Option<ProgressHandler>> = RefCell::new(None);}
pub fn with_progress_handler<R>(handler: ProgressHandler, operation: impl FnOnce() -> R) -> R {
    struct Restore(Option<ProgressHandler>);
    impl Drop for Restore {
        fn drop(&mut self) {
            HANDLER.with(|slot| {
                slot.replace(self.0.take());
            });
        }
    }
    let previous = HANDLER.with(|slot| slot.replace(Some(handler)));
    let _restore = Restore(previous);
    operation()
}
pub fn current_progress_handler() -> Option<ProgressHandler> {
    HANDLER.with(|slot| slot.borrow().clone())
}
pub fn deliver_progress(value: Value, handler: Option<&ProgressHandler>) {
    if let Some(handler) = handler {
        handler(value);
    } else {
        eprintln!("{value}");
    }
}
pub fn emit_progress(value: Value) {
    deliver_progress(value, current_progress_handler().as_ref());
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;
    #[test]
    fn scopes_restore_nested_handlers_and_unwinding() {
        let first = Arc::new(Mutex::new(Vec::new()));
        let second = Arc::new(Mutex::new(Vec::new()));
        let first_sink = first.clone();
        with_progress_handler(
            Arc::new(move |v| first_sink.lock().unwrap().push(v)),
            || {
                emit_progress(1.into());
                let second_sink = second.clone();
                let _ = std::panic::catch_unwind(|| {
                    with_progress_handler(
                        Arc::new(move |v| second_sink.lock().unwrap().push(v)),
                        || {
                            emit_progress(2.into());
                            panic!("simulated worker unwind");
                        },
                    );
                });
                emit_progress(3.into());
            },
        );
        assert_eq!(*first.lock().unwrap(), [Value::from(1), Value::from(3)]);
        assert_eq!(*second.lock().unwrap(), [Value::from(2)]);
        assert!(current_progress_handler().is_none());
    }
}
