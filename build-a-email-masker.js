function maskEmail(email) {
let atIndex = email.indexOf("@")
let username = email.slice(0, atIndex);
let domain = email.slice(atIndex);
let firstChar = username[0];
let lastChar = username[username.length - 1 ] 
let stars = "*".repeat(username.length - 2);
return firstChar + stars + lastChar + domain;
}

let email = "apple.pie@example.com";
console.log(maskEmail(email));


email = "freecodecamp@example.com";
console.log(maskEmail("freecodecamp@example.com"));

email = "info@test.dev";
console.log(maskEmail("info@test.dev"));


email = "user@domain.org";
console.log(maskEmail("user@domain.org"));