import java.awt.BorderLayout;
import java.awt.Dimension;
import java.awt.FlowLayout;
import java.awt.GraphicsEnvironment;
import java.awt.event.ActionEvent;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Scanner;
import javax.swing.BorderFactory;
import javax.swing.DefaultListModel;
import javax.swing.JButton;
import javax.swing.JFrame;
import javax.swing.JLabel;
import javax.swing.JList;
import javax.swing.JOptionPane;
import javax.swing.JPanel;
import javax.swing.JScrollPane;
import javax.swing.JTextField;
import javax.swing.ListSelectionModel;
import javax.swing.SwingUtilities;

/**
 * Enhanced TodoApp with complete UI support (Console Interactive / Headless & Swing GUI).
 * Reuses the core Task model and task operations.
 */
public class TodoApp {

    public static class Task {
        private final int id;
        private String description;
        private boolean completed;

        public Task(int id, String description) {
            this.id = id;
            this.description = description;
            this.completed = false;
        }

        public int getId() {
            return id;
        }

        public String getDescription() {
            return description;
        }

        public void setDescription(String description) {
            this.description = description;
        }

        public boolean isCompleted() {
            return completed;
        }

        public void setCompleted(boolean completed) {
            this.completed = completed;
        }

        @Override
        public String toString() {
            String status = completed ? "[X] Completed" : "[ ] Pending";
            return String.format("%d. %s - %s", id, description, status);
        }
    }

    private final List<Task> tasks = new ArrayList<>();
    private int nextId = 1;

    // --- Core Operations ---

    public Task addTask(String description) {
        if (description == null || description.trim().isEmpty()) {
            throw new IllegalArgumentException("Task description cannot be empty");
        }
        Task task = new Task(nextId++, description.trim());
        tasks.add(task);
        return task;
    }

    public List<Task> getTasks() {
        return Collections.unmodifiableList(tasks);
    }

    public Task getTaskById(int id) {
        for (Task task : tasks) {
            if (task.getId() == id) {
                return task;
            }
        }
        return null;
    }

    public boolean editTask(int id, String newDescription) {
        if (newDescription == null || newDescription.trim().isEmpty()) {
            throw new IllegalArgumentException("New task description cannot be empty");
        }
        Task task = getTaskById(id);
        if (task != null) {
            task.setDescription(newDescription.trim());
            return true;
        }
        return false;
    }

    public boolean completeTask(int id) {
        Task task = getTaskById(id);
        if (task != null) {
            task.setCompleted(true);
            return true;
        }
        return false;
    }

    public boolean deleteTask(int id) {
        for (int i = 0; i < tasks.size(); i++) {
            if (tasks.get(i).getId() == id) {
                tasks.remove(i);
                return true;
            }
        }
        return false;
    }

    public int clearCompleted() {
        int before = tasks.size();
        tasks.removeIf(Task::isCompleted);
        return before - tasks.size();
    }

    public void listTasks() {
        if (tasks.isEmpty()) {
            System.out.println("No tasks found.");
            return;
        }
        for (Task task : tasks) {
            System.out.println(task);
        }
    }

    // --- Swing GUI Implementation (when graphical display is available) ---
    private JFrame frame;
    private JTextField taskInputField;
    private DefaultListModel<String> listModel;
    private JList<String> taskJList;
    private JLabel statusLabel;

    public void initGUI() {
        if (GraphicsEnvironment.isHeadless()) {
            System.out.println("[*] Headless environment detected (Docker/CI). GUI window cannot be displayed.");
            System.out.println("[*] Starting Interactive Console UI with all button actions instead.");
            runConsoleUI(new Scanner(System.in));
            return;
        }

        frame = new JFrame("IntelliCodeX TodoApp");
        frame.setDefaultCloseOperation(JFrame.EXIT_ON_CLOSE);
        frame.setSize(550, 420);
        frame.setLayout(new BorderLayout(10, 10));

        // Top Panel: Task Input
        JPanel topPanel = new JPanel(new BorderLayout(5, 5));
        topPanel.setBorder(BorderFactory.createEmptyBorder(10, 10, 0, 10));
        topPanel.add(new JLabel("Task Description:"), BorderLayout.WEST);
        taskInputField = new JTextField();
        topPanel.add(taskInputField, BorderLayout.CENTER);

        // Center Panel: Task List
        listModel = new DefaultListModel<>();
        taskJList = new JList<>(listModel);
        taskJList.setSelectionMode(ListSelectionModel.SINGLE_SELECTION);
        JScrollPane scrollPane = new JScrollPane(taskJList);
        scrollPane.setBorder(BorderFactory.createTitledBorder("Tasks"));

        // Button Panel: Add, Edit, Complete, Delete, Clear Completed
        JPanel buttonPanel = new JPanel(new FlowLayout(FlowLayout.CENTER, 8, 8));
        JButton btnAdd = new JButton("Add");
        JButton btnEdit = new JButton("Edit");
        JButton btnComplete = new JButton("Complete");
        JButton btnDelete = new JButton("Delete");
        JButton btnClearCompleted = new JButton("Clear Completed");

        buttonPanel.add(btnAdd);
        buttonPanel.add(btnEdit);
        buttonPanel.add(btnComplete);
        buttonPanel.add(btnDelete);
        buttonPanel.add(btnClearCompleted);

        // Status Bar
        statusLabel = new JLabel("Ready. Total tasks: " + tasks.size());
        statusLabel.setBorder(BorderFactory.createEmptyBorder(5, 10, 5, 10));

        // Wire Button Listeners
        btnAdd.addActionListener(this::handleGuiAdd);
        btnEdit.addActionListener(this::handleGuiEdit);
        btnComplete.addActionListener(this::handleGuiComplete);
        btnDelete.addActionListener(this::handleGuiDelete);
        btnClearCompleted.addActionListener(this::handleGuiClearCompleted);

        frame.add(topPanel, BorderLayout.NORTH);
        frame.add(scrollPane, BorderLayout.CENTER);
        JPanel bottomContainer = new JPanel(new BorderLayout());
        bottomContainer.add(buttonPanel, BorderLayout.NORTH);
        bottomContainer.add(statusLabel, BorderLayout.SOUTH);
        frame.add(bottomContainer, BorderLayout.SOUTH);

        refreshGuiList();
        frame.setLocationRelativeTo(null);
        frame.setVisible(true);
    }

    private void refreshGuiList() {
        if (listModel == null) return;
        listModel.clear();
        for (Task t : tasks) {
            listModel.addElement(t.toString());
        }
        statusLabel.setText("Total tasks: " + tasks.size());
    }

    private void handleGuiAdd(ActionEvent e) {
        String input = taskInputField.getText().trim();
        if (input.isEmpty()) {
            JOptionPane.showMessageDialog(frame, "Error: Task description cannot be empty.", "Validation Error", JOptionPane.WARNING_MESSAGE);
            statusLabel.setText("Error: Empty task description.");
            return;
        }
        Task task = addTask(input);
        taskInputField.setText("");
        refreshGuiList();
        statusLabel.setText("Added task #" + task.getId());
    }

    private void handleGuiEdit(ActionEvent e) {
        int idx = taskJList.getSelectedIndex();
        if (idx == -1 || idx >= tasks.size()) {
            JOptionPane.showMessageDialog(frame, "Error: Please select a task from the list to edit.", "Selection Required", JOptionPane.WARNING_MESSAGE);
            statusLabel.setText("Error: Missing task selection.");
            return;
        }
        Task target = tasks.get(idx);
        String updated = JOptionPane.showInputDialog(frame, "Edit task description:", target.getDescription());
        if (updated == null) return; // User cancelled
        if (updated.trim().isEmpty()) {
            JOptionPane.showMessageDialog(frame, "Error: New task description cannot be empty.", "Validation Error", JOptionPane.WARNING_MESSAGE);
            statusLabel.setText("Error: Empty edited description.");
            return;
        }
        editTask(target.getId(), updated.trim());
        refreshGuiList();
        statusLabel.setText("Edited task #" + target.getId());
    }

    private void handleGuiComplete(ActionEvent e) {
        int idx = taskJList.getSelectedIndex();
        if (idx == -1 || idx >= tasks.size()) {
            JOptionPane.showMessageDialog(frame, "Error: Please select a task to mark as completed.", "Selection Required", JOptionPane.WARNING_MESSAGE);
            statusLabel.setText("Error: Missing task selection.");
            return;
        }
        Task target = tasks.get(idx);
        completeTask(target.getId());
        refreshGuiList();
        statusLabel.setText("Completed task #" + target.getId());
    }

    private void handleGuiDelete(ActionEvent e) {
        int idx = taskJList.getSelectedIndex();
        if (idx == -1 || idx >= tasks.size()) {
            JOptionPane.showMessageDialog(frame, "Error: Please select a task to delete.", "Selection Required", JOptionPane.WARNING_MESSAGE);
            statusLabel.setText("Error: Missing task selection.");
            return;
        }
        Task target = tasks.get(idx);
        deleteTask(target.getId());
        refreshGuiList();
        statusLabel.setText("Deleted task #" + target.getId());
    }

    private void handleGuiClearCompleted(ActionEvent e) {
        int count = clearCompleted();
        refreshGuiList();
        if (count == 0) {
            JOptionPane.showMessageDialog(frame, "No completed tasks to clear.", "Clear Completed", JOptionPane.INFORMATION_MESSAGE);
            statusLabel.setText("No completed tasks found.");
        } else {
            statusLabel.setText("Cleared " + count + " completed task(s).");
        }
    }

    // --- Interactive Console UI with All Button Actions ---
    public void runConsoleUI(Scanner scanner) {
        System.out.println("=== TodoApp UI ===");
        System.out.println("Buttons available: [Add] [Edit] [Complete] [Delete] [Clear Completed] [Exit]");
        boolean running = true;
        while (running && scanner.hasNextLine()) {
            String line = scanner.nextLine().trim();
            if (line.isEmpty()) continue;

            String[] parts = line.split("\\s+", 2);
            String action = parts[0].toLowerCase();
            String argument = parts.length > 1 ? parts[1].trim() : "";

            switch (action) {
                case "add":
                    if (argument.isEmpty()) {
                        System.out.println("Error: Task description cannot be empty.");
                    } else {
                        Task task = addTask(argument);
                        System.out.println("Added: " + task);
                    }
                    break;
                case "edit":
                    if (argument.isEmpty()) {
                        System.out.println("Error: Please specify task ID and new description (e.g. 'edit 1 New Title').");
                    } else {
                        String[] editParts = argument.split("\\s+", 2);
                        try {
                            int id = Integer.parseInt(editParts[0]);
                            if (editParts.length < 2 || editParts[1].trim().isEmpty()) {
                                System.out.println("Error: New task description cannot be empty.");
                            } else if (editTask(id, editParts[1])) {
                                System.out.println("Task " + id + " updated.");
                            } else {
                                System.out.println("Error: Task id not found: " + id);
                            }
                        } catch (NumberFormatException ex) {
                            System.out.println("Error: Invalid task id: " + editParts[0]);
                        }
                    }
                    break;
                case "complete":
                    if (argument.isEmpty()) {
                        System.out.println("Error: Please select a task id to complete.");
                    } else {
                        try {
                            int id = Integer.parseInt(argument);
                            if (completeTask(id)) {
                                System.out.println("Task " + id + " marked as completed.");
                            } else {
                                System.out.println("Error: Task id not found: " + id);
                            }
                        } catch (NumberFormatException ex) {
                            System.out.println("Error: Invalid task id: " + argument);
                        }
                    }
                    break;
                case "delete":
                    if (argument.isEmpty()) {
                        System.out.println("Error: Please select a task id to delete.");
                    } else {
                        try {
                            int id = Integer.parseInt(argument);
                            if (deleteTask(id)) {
                                System.out.println("Task " + id + " deleted.");
                            } else {
                                System.out.println("Error: Task id not found: " + id);
                            }
                        } catch (NumberFormatException ex) {
                            System.out.println("Error: Invalid task id: " + argument);
                        }
                    }
                    break;
                case "clear_completed":
                case "clear":
                    int cleared = clearCompleted();
                    if (cleared == 0) {
                        System.out.println("No completed tasks to clear.");
                    } else {
                        System.out.println("Cleared " + cleared + " completed task(s).");
                    }
                    break;
                case "list":
                    listTasks();
                    break;
                case "exit":
                case "quit":
                    running = false;
                    System.out.println("Goodbye!");
                    break;
                default:
                    System.out.println("Unknown action: " + action + ". Buttons available: add, edit, complete, delete, clear, list, exit");
                    break;
            }
        }
    }

    public static void main(String[] args) {
        TodoApp app = new TodoApp();
        if (GraphicsEnvironment.isHeadless()) {
            app.runConsoleUI(new Scanner(System.in));
        } else {
            SwingUtilities.invokeLater(app::initGUI);
        }
    }
}
