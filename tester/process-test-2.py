def convert_temperature(value, unit):
    """
    Convert temperature between Celsius and Fahrenheit.
    :param value: float - The temperature value.
    :param unit: str - 'C' for Celsius or 'F' for Fahrenheit.
    :return: float - Converted temperature.
    """
    if unit == 'C':
        return (value * 9/5) + 32  # Celsius to Fahrenheit
    elif unit == 'F':
        return (value - 32) * 5/9  # Fahrenheit to Celsius
    else:
        raise ValueError("Invalid unit. Use 'C' for Celsius or 'F' for Fahrenheit.")

def word_count(sentence):
    """
    Count the number of words in a sentence.
    :param sentence: str - Input sentence.
    :return: int - Number of words.
    """
    words = sentence.split()
    return len(words)

def find_factors(number):
    """
    Find all factors of a given number.
    :param number: int - The input number.
    :return: list - List of factors.
    """
    if number <= 0:
        raise ValueError("Number must be greater than 0.")
    return [i for i in range(1, number + 1) if number % i == 0]

def fibonacci(n):
    """
    Generate the nth Fibonacci number.
    :param n: int - The position in the Fibonacci sequence.
    :return: int - The nth Fibonacci number.
    """
    if n <= 0:
        raise ValueError("n must be a positive integer.")
    elif n == 1:
        return 0
    elif n == 2:
        return 1
    else:
        a, b = 0, 1
        for _ in range(n - 2):
            a, b = b, a + b
        return b

def are_anagrams(word1, word2):
    """
    Check if two words are anagrams.
    :param word1: str - The first word.
    :param word2: str - The second word.
    :return: bool - True if anagrams, False otherwise.
    """
    return sorted(word1.lower()) == sorted(word2.lower())

def is_prime(n):
    """
    Check if a number is prime.
    :param n: int - The number to check.
    :return: bool - True if prime, False otherwise.
    """
    if n <= 1:
        return False
    for i in range(2, int(n**0.5) + 1):
        if n % i == 0:
            return False
    return True

if __name__ == "__main__":
    # Test convert_temperature
    print(convert_temperature(100, 'C'))  # Should work
    print(convert_temperature(212, 'F'))  # Should work
    # print(convert_temperature(50, 'X'))  # Fatal: Invalid unit

    # Test word_count
    print(word_count("This is a test sentence."))  # Should work
    # print(word_count(None))  # Fatal: NoneType has no split method

    # Test find_factors
    print(find_factors(28))  # Should work
    # print(find_factors(-10))  # Fatal: Negative number raises ValueError

    # Test fibonacci
    print(fibonacci(10))  # Should work
    # print(fibonacci(0))  # Fatal: n must be positive

    # Test are_anagrams
    print(are_anagrams("listen", "silent"))  # Should work
    print(are_anagrams("test", "sett"))  # Should work

    # Test is_prime
    print(is_prime(17))  # Should work
    print(is_prime(18))  # Should work
    # print(is_prime(-5))  # Fatal: Negative number should not be prime
