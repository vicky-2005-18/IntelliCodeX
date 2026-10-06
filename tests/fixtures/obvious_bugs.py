# Test file with obvious bugs for intellicodex testing

def calculate_sum(a, b):
    # Bug 1: Missing import
    return a + b + math.sqrt(a)  # math not imported

def process_data(items):
    # Bug 2: Undefined variable
    result = []
    for item in items:
        result.append(item * multiplier)  # multiplier not defined
    return result

def buggy_function():
    # Bug 3: Syntax error
    print("Hello"
    # Missing closing parenthesis

def another_bug():
    # Bug 4: Type error obvious (runtime/semantic)
    x = "hello"
    y = 5
    return x + y  # Cannot add string and int

if __name__ == "__main__":
    calculate_sum(10, 20)
