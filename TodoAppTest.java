public class TodoAppTest {

    public static void main(String[] args) {
        TodoApp app = new TodoApp();

        // 1. Test Add Task
        TodoApp.Task t1 = app.addTask("First Task");
        if (t1.getId() != 1 || !t1.getDescription().equals("First Task") || t1.isCompleted()) {
            throw new AssertionError("testAddTask failed");
        }
        System.out.println("PASS: testAddTask");

        // 2. Test Add Empty Task Throws
        boolean emptyCaught = false;
        try {
            app.addTask("   ");
        } catch (IllegalArgumentException e) {
            emptyCaught = true;
        }
        if (!emptyCaught) {
            throw new AssertionError("testAddEmptyTask failed to throw IllegalArgumentException");
        }
        System.out.println("PASS: testAddEmptyTask");

        // 3. Test Edit Task
        boolean edited = app.editTask(1, "Updated First Task");
        if (!edited || !app.getTasks().get(0).getDescription().equals("Updated First Task")) {
            throw new AssertionError("testEditTask failed");
        }
        System.out.println("PASS: testEditTask");

        // 4. Test Edit Missing Task
        boolean missingEdit = app.editTask(999, "Non-existent");
        if (missingEdit) {
            throw new AssertionError("testEditMissingTask should return false");
        }
        System.out.println("PASS: testEditMissingTask");

        // 5. Test Complete Task
        boolean completed = app.completeTask(1);
        if (!completed || !app.getTasks().get(0).isCompleted()) {
            throw new AssertionError("testCompleteTask failed");
        }
        System.out.println("PASS: testCompleteTask");

        // 6. Test Complete Missing Task
        boolean missingComplete = app.completeTask(999);
        if (missingComplete) {
            throw new AssertionError("testCompleteMissingTask should return false");
        }
        System.out.println("PASS: testCompleteMissingTask");

        // 7. Test Clear Completed
        TodoApp.Task t2 = app.addTask("Second Task");
        int cleared = app.clearCompleted();
        if (cleared != 1 || app.getTasks().size() != 1 || app.getTasks().get(0).getId() != t2.getId()) {
            throw new AssertionError("testClearCompleted failed");
        }
        System.out.println("PASS: testClearCompleted");

        // 8. Test Delete Task
        boolean deleted = app.deleteTask(t2.getId());
        if (!deleted || !app.getTasks().isEmpty()) {
            throw new AssertionError("testDeleteTask failed");
        }
        System.out.println("PASS: testDeleteTask");

        // 9. Test Delete Missing Task
        boolean missingDelete = app.deleteTask(999);
        if (missingDelete) {
            throw new AssertionError("testDeleteMissingTask should return false");
        }
        System.out.println("PASS: testDeleteMissingTask");

        System.out.println("ALL TESTS PASSED (9/9)");
    }
}
