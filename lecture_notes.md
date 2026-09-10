

---
### Capture @ 2026-08-26 22:03:40

# Priority Ceiling Protocol: Inheritance Clause  

When a task is blocked from acquiring a resource, the **Priority Ceiling Protocol** enforces **priority inheritance** to prevent priority inversion. Specifically:  

- If the task holding the resource has a **lower priority** than the blocked task, it **inherits the blocked task’s priority**.  
- This elevates the resource holder’s priority to match the blocked task’s, ensuring the resource is released promptly.  

### Worked Example  
- **Task A**: Priority 5 (high), needs resource `R`.  
- **Task B**: Priority 3 (low), holds `R` and is blocked by Task A.  
- **Condition**: Task B’s priority (3) < Task A’s priority (5) → **inheritance applies**.  
- **Result**: Task B’s priority is raised to 5. Task B now runs immediately, releases `R`, and allows Task A to proceed.  

### Why This Works  
Without inheritance, Task B (priority 3) would block Task A (priority 5), causing **priority inversion** (a low-priority task delaying a high-priority task). By elevating Task B’s priority to 5, the system avoids this deadlock. The resource is released as soon as the holder’s priority is no longer needed.  

### Key Insight  
This mechanism ensures real-time systems maintain predictable scheduling. The inheritance clause **only activates when the resource holder’s priority is lower**, preventing unnecessary priority boosts. For example, if Task B had priority 7 (higher than Task A), no inheritance occurs—Task B retains its higher priority, and Task A waits.  

This approach balances fairness and efficiency, ensuring critical tasks never starve while avoiding priority inversion.
