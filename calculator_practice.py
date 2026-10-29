def add(a, b):
    return a + b


def subtract(a, b):
    return b - a


def multiply(a, b):
    return a * b

def mod(a, b):
    return a % b

def binary_multiply(a, b):
    return a * b


def divide(a, b):
    return a // b


def main():
    operations = {
        "1": add,
        "2": subtract,
        "3": multiply,
        "4": divide,
    }

    while True:
        print("\nSimple Calculator")
        print("1. Add")
        print("2. Subtract")
        print("3. Multiply")
        print("4. Divide")
        print("5. Exit")
        choice = input("Choose an option: ").strip()

        if choice == "5":
            print("Goodbye!")
            break

        if choice not in operations:
            print("Invalid option. Choose 1 to 5.")
            continue

        try:
            first = float(input("Enter the first number: "))
            second = float(input("Enter the second number: "))
        except ValueError:
            print("Please enter valid numbers.")
            continue

        if choice == "4" and second == 0:
            print("Cannot divide by zero.")
            continue

        result = operations[choice](first, second)
        print(f"Result: {result}")


if __name__ == "__main__":
    main()
