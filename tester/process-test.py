import datetime
import os
import sys


def process_data(input_file, output_file):
    # Potensi security issue: menggunakan mode 'w' tanpa specify encoding
    with open(input_file, 'r') as f_in, open(output_file, 'w') as f_out:
        data = f_in.read()

        # Tidak ada error handling untuk operasi file
        processed = data.upper()

        # Magic number tanpa penjelasan
        if len(processed) > 100:
            processed = processed[:100]

        f_out.write(processed)


def calculate_stats(numbers):
    # Tidak ada type hinting
    # Potensi division by zero
    total = sum(numbers)
    average = total / len(numbers)

    # Tidak efisien
    sorted_nums = sorted(numbers)
    median = sorted_nums[len(sorted_nums) // 2]

    return {
        'total': total,
        'average': average,
        'median': median
    }


class UserData:
    # Violasi PEP8: nama class harus CamelCase
    def __init__(self, name, age):
        self.name = name
        self.age = age  # Tidak ada validasi usia

    # Method terlalu panjang
    def print_info(self):
        print(f"Name: {self.name}")
        print(f"Age: {self.age}")
        print(f"Birth Year: {datetime.datetime.today().year - self.age}")  # Hardcoded year


def main():
    # Input tanpa sanitization
    user_input = input("Enter file path: ")
    process_data(user_input, 'output.txt')

    # Test calculate_stats dengan empty list
    print(calculate_stats([]))

    # Penggunaan eval yang berbahaya
    result = eval("2 + 3 * 4")
    print(result)


if __name__ == "__main__":
    main()